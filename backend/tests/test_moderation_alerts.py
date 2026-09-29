"""Модерация с уведомлениями в MAX: рассылка модераторам, «Одобрить», «Отклонить» с причиной,
повторное нажатие, решение на сайте, правка сообщений других модераторов (editMessage)."""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from arq import Retry
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot import notify as bot_notify
from app.bot.dispatcher import BotContext, handle_update
from app.bot.fsm import MemoryStateStore
from app.core.config import Settings
from app.core.jobs import ALERT_MODERATORS, CLOSE_MODERATION, MemoryJobQueue
from app.integrations.max import MaxClient
from app.models.enums import OrgRole, TrustTier
from app.models.events import Event
from app.models.orgs import OrgMember
from app.models.system import AuditLog
from app.models.users import User
from app.schemas.orgs import VerificationStart
from app.services import moderation as moderation_service
from app.services import verification as verification_service
from app.services.notify import MemoryNotifier, QueuedNotifier
from app.workers import settings as worker
from tests.factories import in_hours, make_event, make_locality, make_org, make_venue, random_area
from tests.helpers import FakeRedis, random_max_id

BASE = "https://max.test"
ADMIN = 777
ADMIN_2 = 778


@pytest.fixture
def settings(db_settings: Settings) -> Settings:
    return db_settings.model_copy(
        update={
            "admin_max_user_ids": [ADMIN, ADMIN_2],
            "public_base_url": "https://afisha.test",
            "max_bot_username": "afisha_bot",
        }
    )


@pytest.fixture
def bot(db_app: FastAPI, settings: Settings) -> BotContext:
    return BotContext(
        settings=settings,
        db=db_app.state.db,
        max=MaxClient("tkn", BASE, retries=0, backoff_s=0),
        states=MemoryStateStore(),
        notifier=MemoryNotifier(),
        redis=FakeRedis(),
    )


@pytest.fixture
def max_api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/messages", name="send").respond(
            200, json={"message": {"body": {"mid": "mid.x", "seq": 1}}}
        )
        mock.put("/messages", name="edit").respond(200, json={"success": True})
        mock.post("/answers", name="answer").respond(200, json={"success": True})
        yield mock


def _callback(user_id: int, payload: str) -> dict[str, Any]:
    return {
        "update_type": "message_callback",
        "timestamp": 2,
        "callback": {
            "timestamp": 2,
            "callback_id": f"cb-{uuid.uuid4().hex[:6]}",
            "payload": payload,
            "user": {"user_id": user_id, "first_name": "Модератор", "is_bot": False},
        },
        "message": {"recipient": {"chat_id": 42, "chat_type": "dialog"}},
    }


def _text(user_id: int, text: str) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "timestamp": 3,
        "message": {
            "sender": {"user_id": user_id, "first_name": "Модератор", "is_bot": False},
            "recipient": {"chat_id": 42, "chat_type": "dialog"},
            "timestamp": 3,
            "body": {"mid": "m1", "seq": 1, "text": text},
        },
    }


def _answers(max_api: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(c.request.content) for c in max_api["answer"].calls]


def _sent(max_api: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(c.request.content) for c in max_api["send"].calls]


def _buttons(message: dict[str, Any]) -> list[dict[str, Any]]:
    rows = message["attachments"][0]["payload"]["buttons"]
    return [button for row in rows for button in row]


async def _pending_event(db_session: AsyncSession) -> tuple[Event, User]:
    lat, lon = random_area()
    locality = await make_locality(
        db_session, f"Модерово{uuid.uuid4().hex[:6]}", lat, lon, timezone="Asia/Yekaterinburg"
    )
    venue = await make_venue(db_session, locality, lat, lon, name="Клуб «Искра»")
    author = User(max_user_id=random_max_id(), first_name="Ира", channel="max")
    db_session.add(author)
    await db_session.flush()
    event = await make_event(
        db_session,
        locality,
        title="Ярмарка",
        venue=venue,
        starts=[in_hours(30)],
        trust_tier=TrustTier.community,
        status="pending",
        author_user_id=author.id,
        moderation_reason="похоже на рекламу; мало информации о событии",
    )
    await db_session.commit()
    return event, author


async def test_flagged_event_goes_to_moderators(db_session: AsyncSession) -> None:
    event, _ = await _pending_event(db_session)
    event.description = "СКИДКИ ТОЛЬКО СЕГОДНЯ!!! Промокод"
    await db_session.commit()
    notifier = MemoryNotifier()
    status = await moderation_service.moderate_event(db_session, event.id, notifier=notifier)
    assert status == "pending"
    assert notifier.moderation == [("alert", "e", event.id)]

    # Через очередь — задача с job_id: повторная постановка не дублирует рассылку.
    jobs = MemoryJobQueue()
    await QueuedNotifier(jobs).alert_moderators("e", event.id)
    assert [(j.name, j.job_id) for j in jobs.jobs] == [(ALERT_MODERATORS, f"mod:e:{event.id}")]


async def test_broadcast_to_all_moderators(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    max_api["send"].mock(
        side_effect=[
            httpx.Response(200, json={"message": {"body": {"mid": "mid.777", "seq": 1}}}),
            httpx.Response(500, json={"code": "boom", "message": "boom"}),
        ]
    )
    failed = await bot_notify.alert_moderators(
        bot.db, bot.max, bot.settings, bot.redis, "e", event.id
    )
    # Ошибка у одного модератора не мешает остальным; ему — повтор задачи.
    assert failed == [ADMIN_2]
    calls = max_api["send"].calls
    assert [c.request.url.params["user_id"] for c in calls] == [str(ADMIN), str(ADMIN_2)]
    message = json.loads(calls[0].request.content)
    text = message["text"]
    for part in ("Ярмарка", "Клуб «Искра»", "Модерово", "Ира", "похоже на рекламу"):
        assert part in text
    assert _buttons(message) == [
        {"type": "callback", "text": texts.MOD_APPROVE, "payload": f"mod:e:{event.id}:approve"},
        {"type": "callback", "text": texts.MOD_REJECT, "payload": f"mod:e:{event.id}:reject"},
        {
            "type": "callback",
            "text": texts.ADMIN_DELETE_BUTTON,
            "payload": f"adm:e:{event.id}:delete",
        },
        # Из бота — только мини-приложение, не сайт.
        {
            "type": "open_app",
            "text": texts.MOD_OPEN_APP,
            "web_app": "afisha_bot",
            "payload": f"mod_{event.id}",
        },
    ]

    # Повтор задачи: дошедшему модератору второй раз не пишем.
    max_api["send"].mock(
        return_value=httpx.Response(200, json={"message": {"body": {"mid": "mid.778"}}})
    )
    failed = await bot_notify.alert_moderators(
        bot.db, bot.max, bot.settings, bot.redis, "e", event.id
    )
    assert failed == []
    assert max_api["send"].calls.last.request.url.params["user_id"] == str(ADMIN_2)
    assert len(max_api["send"].calls) == 3
    assert bot.redis.hashes[bot_notify.moderation_key("e", event.id)] == {
        str(ADMIN): "mid.777",
        str(ADMIN_2): "mid.778",
    }


async def test_event_time_in_locality_timezone(bot: BotContext, db_session: AsyncSession) -> None:
    from app.bot import render
    from app.models.events import EventSession

    event, _ = await _pending_event(db_session)
    starts_at = await db_session.scalar(
        select(EventSession.starts_at).where(EventSession.event_id == event.id)
    )
    assert starts_at is not None
    card = await bot_notify.moderation_card(bot.db, "e", event.id)
    assert card is not None
    assert render.when(starts_at, "Asia/Yekaterinburg") in card.text


async def test_worker_job_retries_undelivered(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    max_api["send"].respond(500, json={"code": "boom", "message": "boom"})
    with pytest.raises(Retry):
        await worker.alert_moderators({"bot": bot, "job_try": 1}, "e", event.id)
    # Последняя попытка — без исключения, только лог.
    assert (
        await worker.alert_moderators({"bot": bot, "job_try": worker.SEND_TRIES}, "e", event.id)
        == 2
    )


async def test_org_verification_goes_to_moderators(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, f"Орлово{uuid.uuid4().hex[:6]}", lat, lon)
    org = await make_org(db_session, verified=False)
    org.locality_id = locality.id
    org.phone = "+79990001122"
    org.website = "https://dk.example"
    owner = User(max_user_id=random_max_id(), first_name="Пётр", channel="max")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(OrgMember(org_id=org.id, user_id=owner.id, role=OrgRole.owner))
    await db_session.commit()

    notifier = MemoryNotifier()
    request = await verification_service.start(
        db_session,
        owner,
        org.id,
        VerificationStart(method="manual", inn="7707083893"),
        notifier=notifier,
    )
    assert ("alert", "v", request.id) in notifier.moderation

    await bot_notify.alert_moderators(bot.db, bot.max, bot.settings, bot.redis, "v", request.id)
    message = _sent(max_api)[0]
    for part in ("Дом культуры", "7707083893", "Орлово", "+79990001122", "Пётр"):
        assert part in message["text"]
    assert _buttons(message)[0]["payload"] == f"mod:v:{request.id}:approve"
    assert _buttons(message)[-1] == {
        "type": "open_app",
        "text": texts.MOD_OPEN_APP,
        "web_app": "afisha_bot",
        "payload": "mod_0",
    }

    # Одобрить → заявка verified, владельцу уведомление, решение в audit_log.
    await handle_update(bot, _callback(ADMIN, f"mod:v:{request.id}:approve"))
    assert _answers(max_api)[-1]["notification"] == texts.MOD_APPROVED.format(id=request.id)
    await db_session.refresh(request)
    assert request.status == "verified"
    assert bot.notifier.sent and bot.notifier.sent[-1][0] == owner.id  # type: ignore[union-attr]
    assert ("closed", "v", request.id) in bot.notifier.moderation  # type: ignore[union-attr]
    # Повторное нажатие любой кнопки — «уже решено».
    await handle_update(bot, _callback(ADMIN_2, f"mod:v:{request.id}:reject"))
    assert _answers(max_api)[-1]["notification"] == "Уже решено: одобрено"


async def test_approve_notifies_author_and_audits(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, author = await _pending_event(db_session)
    await handle_update(bot, _callback(ADMIN, f"mod:e:{event.id}:approve"))

    assert _answers(max_api)[-1]["notification"] == texts.MOD_APPROVED.format(id=event.id)
    await db_session.refresh(event)
    assert event.status == "published"
    notifier: MemoryNotifier = bot.notifier  # type: ignore[assignment]
    assert (author.id, texts.EVENT_PUBLISHED.format(title="Ярмарка")) in [
        (u, t) for u, t, _ in notifier.sent
    ]
    assert ("closed", "e", event.id) in notifier.moderation
    audit = await db_session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "event", AuditLog.entity_id == event.id)
    )
    assert any(a.actor_type == "admin" for a in audit)


async def test_reject_asks_reason_and_notifies_author(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, author = await _pending_event(db_session)
    await handle_update(bot, _callback(ADMIN, f"mod:e:{event.id}:reject"))
    # Без тоста POST /answers не шлём (MAX отклоняет пустой ответ), причина — сообщением.
    assert _answers(max_api) == []
    assert _sent(max_api)[-1]["text"] == texts.MOD_ASK_REASON
    await db_session.refresh(event)
    assert event.status == "pending"

    await handle_update(bot, _text(ADMIN, "нет"))
    assert _sent(max_api)[-1]["text"] == texts.QUEUE_REASON_TOO_SHORT

    await handle_update(bot, _text(ADMIN, "Это реклама магазина, а не событие"))
    assert _sent(max_api)[-1]["text"] == texts.MOD_REJECTED.format(id=event.id)
    await db_session.refresh(event)
    assert event.status == "rejected"
    assert event.moderation_reason == "Это реклама магазина, а не событие"
    notifier: MemoryNotifier = bot.notifier  # type: ignore[assignment]
    to_author = [t for u, t, _ in notifier.sent if u == author.id]
    assert to_author and "Это реклама магазина" in to_author[-1]
    assert ("closed", "e", event.id) in notifier.moderation


async def test_repeated_press_says_already_decided(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    await handle_update(bot, _callback(ADMIN, f"mod:e:{event.id}:approve"))
    notifier: MemoryNotifier = bot.notifier  # type: ignore[assignment]
    sent_before = len(notifier.sent)

    await handle_update(bot, _callback(ADMIN, f"mod:e:{event.id}:approve"))
    assert _answers(max_api)[-1]["notification"] == "Уже решено: одобрено"
    # Второй модератор жмёт «Отклонить» — причину не спрашиваем, статус не меняется.
    sends = len(max_api["send"].calls)
    await handle_update(bot, _callback(ADMIN_2, f"mod:e:{event.id}:reject"))
    assert _answers(max_api)[-1]["notification"] == "Уже решено: одобрено"
    assert len(max_api["send"].calls) == sends
    await db_session.refresh(event)
    assert event.status == "published"
    assert len(notifier.sent) == sent_before


async def test_decided_on_site_then_button(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    admin = User(max_user_id=random_max_id(), first_name="Админ", channel="max")
    db_session.add(admin)
    await db_session.commit()
    notifier = MemoryNotifier()
    await moderation_service.admin_decide(
        db_session, admin, event.id, "reject", "Дубль события", notifier
    )
    assert ("closed", "e", event.id) in notifier.moderation

    await handle_update(bot, _callback(ADMIN, f"mod:e:{event.id}:approve"))
    assert _answers(max_api)[-1]["notification"] == "Уже решено: отклонено"
    await db_session.refresh(event)
    assert event.status == "rejected"


async def test_not_moderator_cannot_decide(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    await handle_update(bot, _callback(random_max_id(), f"mod:e:{event.id}:approve"))
    assert _answers(max_api)[-1]["notification"] == texts.ADMIN_ONLY
    await db_session.refresh(event)
    assert event.status == "pending"


async def test_close_edits_all_moderator_messages(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    await bot.redis.hset(bot_notify.moderation_key("e", event.id), str(ADMIN), "mid.1")
    await bot.redis.hset(bot_notify.moderation_key("e", event.id), str(ADMIN_2), "mid.2")
    # Пока заявка ждёт — править нечего.
    assert await worker.close_moderation({"bot": bot}, "e", event.id) == 0
    assert not max_api["edit"].called

    event.status = "published"
    await db_session.commit()
    assert await worker.close_moderation({"bot": bot}, "e", event.id) == 0
    edits = max_api["edit"].calls
    assert sorted(c.request.url.params["message_id"] for c in edits) == ["mid.1", "mid.2"]
    body = json.loads(edits[0].request.content)
    assert body["text"].endswith("Решено: одобрено")
    # Кнопки решения убраны, карточка в мини-приложении осталась.
    assert _buttons(body) == [
        {
            "type": "open_app",
            "text": texts.MOD_OPEN_APP,
            "web_app": "afisha_bot",
            "payload": f"mod_{event.id}",
        }
    ]
    assert bot_notify.moderation_key("e", event.id) not in bot.redis.hashes

    jobs = MemoryJobQueue()
    await QueuedNotifier(jobs).moderation_closed("e", event.id)
    assert jobs.jobs[0].name == CLOSE_MODERATION


async def test_whoami_for_moderator(bot: BotContext, max_api: respx.MockRouter) -> None:
    await handle_update(bot, _text(ADMIN, "/whoami"))
    reply = _sent(max_api)[-1]["text"]
    assert str(ADMIN) in reply and texts.MYID_ADMIN in reply
    assert keyboards.P_MOD == "mod"


async def test_clean_event_is_not_auto_published(db_session: AsyncSession) -> None:
    # Правила ничего не нашли — всё равно ждём решения человека (§6).
    event, _ = await _pending_event(db_session)
    event.moderation_reason = None
    await db_session.commit()
    notifier = MemoryNotifier()
    status = await moderation_service.moderate_event(db_session, event.id, notifier=notifier)
    assert status == "pending"
    await db_session.refresh(event)
    assert event.status == "pending"
    assert notifier.moderation == [("alert", "e", event.id)]


async def test_official_event_also_waits_for_moderator(db_session: AsyncSession) -> None:
    event, _ = await _pending_event(db_session)
    event.trust_tier = TrustTier.official
    await db_session.commit()
    notifier = MemoryNotifier()
    assert await moderation_service.moderate_event(db_session, event.id, notifier=notifier) == (
        "pending"
    )
    assert notifier.moderation == [("alert", "e", event.id)]


async def test_admin_delete_audits_and_notifies(db_session: AsyncSession) -> None:
    from app.core.errors import AppError
    from app.models.events import EventSession

    event, author = await _pending_event(db_session)
    event_id = event.id
    admin = User(max_user_id=random_max_id(), first_name="Админ", channel="max")
    db_session.add(admin)
    await db_session.commit()
    admin_id, author_id = admin.id, author.id
    notifier = MemoryNotifier()
    await moderation_service.admin_delete(db_session, admin, event_id, "Дубль", notifier)

    db_session.expire_all()
    assert await db_session.get(Event, event_id) is None
    # Сеансы ушли каскадом.
    assert (
        await db_session.scalar(select(EventSession.id).where(EventSession.event_id == event_id))
        is None
    )
    audit = (
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "event",
                AuditLog.entity_id == event_id,
                AuditLog.action == "event.admin_delete",
            )
        )
    ).all()
    assert len(audit) == 1
    assert audit[0].actor_type == "admin" and audit[0].actor_user_id == admin_id
    assert audit[0].diff is not None and audit[0].diff["reason"] == "Дубль"
    assert (author_id, texts.EVENT_DELETED_BY_ADMIN.format(title="Ярмарка", reason="Дубль")) in [
        (u, t) for u, t, _ in notifier.sent
    ]
    assert ("closed", "e", event_id) in notifier.moderation

    with pytest.raises(AppError) as exc:
        await moderation_service.admin_delete(db_session, admin, event_id, None, notifier)
    assert exc.value.status_code == 404


async def test_bot_delete_asks_confirmation(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    event_id = event.id
    await handle_update(bot, _callback(ADMIN, f"adm:e:{event_id}:delete"))
    ask = _sent(max_api)[-1]
    assert ask["text"] == texts.ADMIN_DELETE_ASK.format(id=event_id, title="Ярмарка")
    assert [b["payload"] for b in _buttons(ask)] == [
        f"adm:e:{event_id}:delyes",
        f"adm:e:{event_id}:delno",
    ]
    # Отмена — событие на месте.
    await handle_update(bot, _callback(ADMIN, f"adm:e:{event_id}:delno"))
    assert _answers(max_api)[-1]["notification"] == texts.ADMIN_DELETE_CANCELLED
    assert await db_session.get(Event, event_id) is not None

    await handle_update(bot, _callback(ADMIN, f"adm:e:{event_id}:delyes"))
    assert _sent(max_api)[-1]["text"] == texts.ADMIN_DELETE_DONE.format(id=event_id)
    db_session.expire_all()
    assert await db_session.get(Event, event_id) is None


async def test_del_command(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    await handle_update(bot, _text(random_max_id(), f"/del {event.id}"))
    assert _sent(max_api)[-1]["text"] == texts.ADMIN_ONLY
    await handle_update(bot, _text(ADMIN, "/del abc"))
    assert _sent(max_api)[-1]["text"] == texts.ADMIN_DELETE_USAGE
    await handle_update(bot, _text(ADMIN, f"/del #{event.id}"))
    assert _sent(max_api)[-1]["text"] == texts.ADMIN_DELETE_ASK.format(id=event.id, title="Ярмарка")


async def test_close_after_delete(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    event, _ = await _pending_event(db_session)
    event_id = event.id
    await bot.redis.hset(bot_notify.moderation_key("e", event_id), str(ADMIN), "mid.1")
    await db_session.delete(event)
    await db_session.commit()
    assert await worker.close_moderation({"bot": bot}, "e", event_id) == 0
    body = json.loads(max_api["edit"].calls.last.request.content)
    assert body["text"].endswith(texts.MOD_VERDICTS["deleted"])
    assert body["attachments"] == []
