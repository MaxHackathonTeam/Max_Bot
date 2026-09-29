"""Сценарии бота (§12) на настоящей БД; API MAX подменён respx."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.dispatcher import BotContext, handle_update, parse_start_payload
from app.bot.fsm import MemoryStateStore
from app.bot.notify import BotNotifier
from app.core.config import Settings
from app.core.jobs import MemoryJobQueue
from app.integrations.max import MaxClient
from app.models.enums import TrustTier
from app.models.events import Event, EventSession
from app.models.geo import Locality
from app.models.system import AuditLog
from app.models.users import User
from app.services import users as users_service
from app.services.notify import QueuedNotifier
from tests.factories import make_event, make_locality, make_org, make_venue, random_area
from tests.helpers import random_max_id

BASE = "https://max.test"


@pytest.fixture
def bot(db_app: FastAPI, db_settings: Settings) -> BotContext:
    client = MaxClient("tkn", BASE, retries=0, backoff_s=0)
    return BotContext(
        settings=db_settings, db=db_app.state.db, max=client, states=MemoryStateStore()
    )


@pytest.fixture
def max_api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/messages", name="send").respond(200, json={"message": {}})
        mock.post("/answers", name="answer").respond(200, json={"success": True})
        yield mock


def _sent(max_api: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(c.request.content) for c in max_api["send"].calls]


def _buttons(message: dict[str, Any]) -> list[dict[str, Any]]:
    rows = message["attachments"][0]["payload"]["buttons"]
    return [button for row in rows for button in row]


def _started(user_id: int, payload: str | None = None) -> dict[str, Any]:
    return {
        "update_type": "bot_started",
        "timestamp": 1,
        "chat_id": 5000 + user_id % 1000,
        "user": {"user_id": user_id, "first_name": "Маша", "is_bot": False},
        "payload": payload,
    }


def _callback(user_id: int, payload: str) -> dict[str, Any]:
    return {
        "update_type": "message_callback",
        "timestamp": 2,
        "callback": {
            "callback_id": "cb-1",
            "payload": payload,
            "user": {"user_id": user_id, "first_name": "Маша"},
        },
        "message": {"recipient": {"chat_id": 42, "chat_type": "dialog"}},
    }


def _text(
    user_id: int,
    text: str | None,
    chat_type: str = "dialog",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"mid": "m1", "text": text}
    if attachments:
        body["attachments"] = attachments
    return {
        "update_type": "message_created",
        "timestamp": 3,
        "message": {
            "sender": {"user_id": user_id, "first_name": "Маша"},
            "recipient": {"chat_id": 42, "chat_type": chat_type},
            "body": body,
        },
    }


def _answers(max_api: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(c.request.content) for c in max_api["answer"].calls]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("ev_123", "ev_123"),
        (" org_7 ", "org_7"),
        ("inv_AbCdEf12_-", "inv_AbCdEf12_-"),
        ("feed_weekend", "feed_weekend"),
        ("feed_other", None),
        ("ev_", None),
        ("ev_1; drop", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_start_payload(payload: str | None, expected: str | None) -> None:
    assert parse_start_payload(payload) == expected


async def test_start_greets_and_asks_place(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    user_id = random_max_id()
    await handle_update(bot, _started(user_id))

    # bot_started → приветствие с меню и сразу выбор населённого пункта.
    menu, ask = _sent(max_api)
    assert menu["text"].startswith("Привет, Маша!")
    labels = [b["text"] for b in _buttons(menu)]
    assert labels[:3] == [texts.MENU_FIND, texts.MENU_ADD, texts.MENU_CITY_NONE]
    assert _buttons(menu)[-1] == {
        "type": "open_app",
        "text": texts.MENU_OPEN_APP,
        "web_app": "afisha_test_bot",
    }
    assert ask["text"] == texts.ASK_LOCALITY
    assert _buttons(ask)[0]["type"] == "request_geo_location"
    request = max_api["send"].calls.last.request
    assert request.url.params["chat_id"] == str(5000 + user_id % 1000)

    user = await users_service.get_by_max_id(db_session, user_id)
    assert user is not None
    assert user.bot_started_at is not None
    assert user.dialog_chat_id == 5000 + user_id % 1000


async def test_start_with_deeplink_sends_open_app_payload(
    bot: BotContext, max_api: respx.MockRouter
) -> None:
    await handle_update(bot, _started(random_max_id(), payload="ev_42"))
    deeplink = _sent(max_api)[0]
    assert deeplink["text"] == texts.DEEPLINK_EVENT
    assert _buttons(deeplink)[0]["payload"] == "ev_42"


async def test_consent_callback_saves_and_answers(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    user_id = random_max_id()
    await handle_update(bot, _callback(user_id, keyboards.CB_CONSENT_ACCEPT))

    answer = max_api["answer"].calls.last.request
    assert json.loads(answer.content) == {"notification": texts.CONSENT_ACCEPTED_TOAST}
    assert answer.url.params["callback_id"] == "cb-1"
    # Места ещё нет — онбординг спрашивает населённый пункт.
    ask = _sent(max_api)[-1]
    assert ask["text"] == texts.ASK_LOCALITY
    assert _buttons(ask)[0]["type"] == "request_geo_location"

    user = await users_service.get_by_max_id(db_session, user_id)
    assert user is not None
    assert await users_service.has_required_consents(db_session, user)

    # После согласия /start сразу показывает меню без повторного запроса согласия.
    before = len(_sent(max_api))
    await handle_update(bot, _text(user_id, "/start"))
    menu, ask_again = _sent(max_api)[before:]
    assert menu["text"].startswith("Привет, Маша!")
    assert _buttons(menu)[0]["payload"] == keyboards.CB_FIND
    assert ask_again["text"] == texts.ASK_LOCALITY


async def test_org_menu_opens_cabinet(bot: BotContext, max_api: respx.MockRouter) -> None:
    await handle_update(bot, _callback(random_max_id(), keyboards.CB_ORG))
    (message,) = _sent(max_api)
    assert message["text"] == texts.ORG_MENU
    payloads = [b.get("payload") for b in _buttons(message) if b["type"] == "open_app"]
    assert payloads == ["org_0", "draft_0"]


async def test_help_and_unknown_text(bot: BotContext, max_api: respx.MockRouter) -> None:
    user_id = random_max_id()
    await handle_update(bot, _text(user_id, "/help"))
    await handle_update(bot, _text(user_id, "абырвалг"))
    await handle_update(bot, _text(user_id, "/nope"))
    help_msg, unknown, command = _sent(max_api)
    assert help_msg["text"] == texts.HELP
    # Непонятный ввод — подсказка и меню.
    assert unknown["text"] == texts.UNKNOWN_TEXT
    assert _buttons(unknown)[0]["payload"] == keyboards.CB_FIND
    assert command["text"] == texts.UNKNOWN_COMMAND


async def test_group_messages_ignored(bot: BotContext, max_api: respx.MockRouter) -> None:
    await handle_update(bot, _text(random_max_id(), "/start", chat_type="chat"))
    assert _sent(max_api) == []


async def test_error_handler_reports_to_user(bot: BotContext, max_api: respx.MockRouter) -> None:
    max_api["send"].mock(
        side_effect=[
            httpx.Response(400, json={"code": "boom", "message": "boom"}),
            httpx.Response(200, json={"message": {}}),
        ]
    )
    await handle_update(bot, _callback(random_max_id(), keyboards.CB_MENU))
    error = _sent(max_api)[-1]
    assert error["text"] == texts.ERROR
    assert _buttons(error)[0]["payload"] == keyboards.CB_MENU
    # callback уже был отвечен до ошибки — повторно не отвечаем.
    assert max_api["answer"].call_count == 1


# --- Онбординг, подборки, «Пойду», настройки (этап 2) ---------------------------------


def _unique(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


async def _user(session: AsyncSession, user_id: int) -> User:
    # Бот пишет в БД своей сессией — перечитываем пользователя, не трогая остальные объекты.
    user = await session.scalar(
        select(User).where(User.max_user_id == user_id).execution_options(populate_existing=True)
    )
    assert user is not None
    return user


async def _ready_user(bot: BotContext, session: AsyncSession, locality: Locality | None) -> int:
    """Пользователь с согласием и (если передан) населённым пунктом."""
    user_id = random_max_id()
    await handle_update(bot, _callback(user_id, keyboards.CB_CONSENT_ACCEPT))
    if locality is not None:
        await users_service.set_location(session, await _user(session, user_id), locality.id)
    return user_id


async def test_onboarding_by_text_and_interests(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    name = _unique("Берёзовка")
    locality = await make_locality(db_session, name, lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, None)

    await handle_update(bot, _text(user_id, name))
    choose = _sent(max_api)[-1]
    assert choose["text"] == texts.LOCALITY_CHOOSE
    assert {
        "type": "callback",
        "text": f"{name}, Тестовая область",
        "payload": f"loc:{locality.id}",
    } in _buttons(choose)

    before = len(_sent(max_api))
    await handle_update(bot, _callback(user_id, f"loc:{locality.id}"))
    saved, interests = _sent(max_api)[before:]
    assert saved["text"] == texts.LOCALITY_SAVED.format(name=name)
    assert interests["text"] == texts.ASK_INTERESTS

    await handle_update(bot, _callback(user_id, "int:concert"))
    edited = _answers(max_api)[-1]["message"]
    labels = [b["text"] for b in _buttons(edited)]
    assert "✅ Концерты" in labels

    await handle_update(bot, _callback(user_id, "int:done"))
    assert _sent(max_api)[-1]["text"] == texts.INTERESTS_SAVED

    user = await _user(db_session, user_id)
    assert user.locality_id == locality.id
    assert user.interests == ["concert"]
    # Состояние сброшено: текст без признаков запроса — «пока понимаю только команды».
    await handle_update(bot, _text(user_id, "привет, как дела"))
    assert _sent(max_api)[-1]["text"] == texts.UNKNOWN_TEXT


async def test_onboarding_by_geolocation(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Сосновка"), lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, None)

    geo = [{"type": "location", "latitude": lat + 0.01, "longitude": lon}]
    await handle_update(bot, _text(user_id, None, attachments=geo))
    assert _sent(max_api)[-1]["text"] == texts.ASK_INTERESTS

    user = await _user(db_session, user_id)
    assert user.locality_id == locality.id
    assert user.home_point is not None
    diff = await db_session.scalar(
        select(AuditLog.diff)
        .where(AuditLog.entity_id == user.id, AuditLog.action == "user.update_profile")
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    # Координаты в журнал не пишем.
    assert diff is not None
    assert diff["locality_id"] == [None, locality.id]
    assert f"{lat:.3f}"[:6] not in json.dumps(diff)


async def test_unknown_locality_text(bot: BotContext, max_api: respx.MockRouter) -> None:
    user_id = random_max_id()
    await handle_update(bot, _callback(user_id, keyboards.CB_CONSENT_ACCEPT))
    await handle_update(bot, _text(user_id, "Несуществующеград"))
    reply = _sent(max_api)[-1]
    assert reply["text"].startswith("Не нашёл «Несуществующеград»")
    assert _buttons(reply)[0]["type"] == "request_geo_location"


async def test_pushkin_feed_pages_and_save(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Липовка"), lat, lon)
    venue = await make_venue(db_session, locality, lat, lon, name="Клуб")
    org = await make_org(db_session)
    for i in range(7):
        await make_event(
            db_session,
            locality,
            title=f"Пушкинское {i}",
            venue=venue,
            org=org,
            starts=[datetime.now(UTC) + timedelta(days=1, hours=i)],
            pushkin_card=True,
            price_type="paid",
            price_min=Decimal(300),
            price_max=Decimal(300),
        )
    await make_event(
        db_session,
        locality,
        title="Соседское",
        trust_tier=TrustTier.community,
        pushkin_card=True,
    )
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, locality)

    await handle_update(bot, _callback(user_id, keyboards.CB_PUSHKIN))
    official, community = _sent(max_api)[-2:]
    # Ленты не смешиваются: официальные и от сообщества — отдельными сообщениями.
    assert "Соседское" in community["text"] and "Пушкинское" not in community["text"]
    first = official
    assert "1. " in first["text"] and "Пушкинское 0" in first["text"]
    assert "300 ₽ · 💳" in first["text"]
    assert "Соседское" not in first["text"]
    buttons = _buttons(first)
    assert buttons[0] == {
        "type": "open_app",
        "text": texts.FEED_DETAILS_BUTTON.format(n=1),
        "web_app": "afisha_test_bot",
        "payload": buttons[0]["payload"],
    }
    assert buttons[0]["payload"].startswith("ev_")
    save = next(b for b in buttons if b["payload"].startswith("save:"))
    more = next(b for b in buttons if b["text"] == texts.FEED_MORE_BUTTON)
    assert more["payload"].startswith("feed:pushkin:30:o:5:")
    assert all(len(b.get("payload", "")) <= 1024 for b in buttons)

    await handle_update(bot, _callback(user_id, more["payload"]))
    second = _sent(max_api)[-1]
    assert "6. " in second["text"] and "7. " in second["text"]
    assert not any(b["text"] == texts.FEED_MORE_BUTTON for b in _buttons(second))

    await handle_update(bot, _callback(user_id, save["payload"]))
    assert _answers(max_api)[-1] == {"notification": texts.SAVED_TOAST}
    # Повторное нажатие идемпотентно.
    await handle_update(bot, _callback(user_id, save["payload"]))
    assert _answers(max_api)[-1] == {"notification": texts.SAVED_TOAST}

    await handle_update(bot, _text(user_id, "/saved"))
    saved = _sent(max_api)[-1]
    assert saved["text"].startswith(texts.SAVED_HEADER)
    assert "Пушкинское 0" in saved["text"]
    unsave = next(b for b in _buttons(saved) if b["payload"].startswith("unsave:"))

    await handle_update(bot, _callback(user_id, unsave["payload"]))
    answer = _answers(max_api)[-1]
    assert answer["notification"] == texts.UNSAVED_TOAST
    assert answer["message"]["text"] == texts.SAVED_EMPTY


async def test_feed_empty_offers_wider_radius(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Пустошь"), lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, locality)

    before = len(_sent(max_api))
    await handle_update(bot, _text(user_id, "/today"))
    # Дальше могут идти ближайшие события из других тестов — смотрим первое сообщение.
    empty = _sent(max_api)[before]
    assert empty["text"].startswith(texts.EMPTY_HERE)
    payloads = [b["payload"] for b in _buttons(empty)]
    assert payloads[:2] == [keyboards.CB_ADD, "feed:today:50:o:0"]


async def test_feed_without_locality_asks_place(bot: BotContext, max_api: respx.MockRouter) -> None:
    user_id = random_max_id()
    await handle_update(bot, _text(user_id, "/weekend"))
    reply = _sent(max_api)[-1]
    assert reply["text"].startswith(texts.NEED_LOCALITY)
    assert _buttons(reply)[0]["type"] == "request_geo_location"


async def test_broken_feed_payload_is_ignored(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Ольховка"), lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, locality)
    before = len(_sent(max_api))
    await handle_update(bot, _callback(user_id, "feed:today:31:0"))
    # Непонятная кнопка — «устарела» и меню, а не молчание.
    assert _answers(max_api)[-1] == {"notification": texts.FEED_EXPIRED_TOAST}
    (menu,) = _sent(max_api)[before:]
    assert _buttons(menu)[0]["payload"] == keyboards.CB_FIND
    await handle_update(bot, _callback(user_id, "feed:today:30:0:bad-cursor"))
    assert _sent(max_api)[-1]["text"] == texts.FEED_EXPIRED_TOAST


async def test_save_without_consent_asks_consent(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Ивановка"), lat, lon)
    event = await make_event(db_session, locality)
    session_id = await db_session.scalar(
        select(EventSession.id).where(EventSession.event_id == event.id)
    )
    await db_session.commit()

    await handle_update(bot, _callback(random_max_id(), f"save:{event.id}:{session_id}"))
    assert _answers(max_api)[-1]["notification"].startswith("Чтобы сохранять события")
    assert _buttons(_sent(max_api)[-1])[0]["payload"] == keyboards.CB_CONSENT_ACCEPT


async def test_settings_radius_toggles_and_delete(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    name = _unique("Дубки")
    locality = await make_locality(db_session, name, lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, locality)

    await handle_update(bot, _text(user_id, "/settings"))
    view = _sent(max_api)[-1]
    assert f"Место: {name}" in view["text"]
    assert "Радиус: 30 км" in view["text"]

    await handle_update(bot, _callback(user_id, "rad:5"))
    edited = _answers(max_api)[-1]["message"]
    assert "Радиус: 5 км" in edited["text"]
    assert "• 5 км •" in [b["text"] for b in _buttons(edited)]
    await handle_update(bot, _callback(user_id, keyboards.CB_SET_REMINDERS))
    assert "Напоминания: выкл" in _answers(max_api)[-1]["message"]["text"]
    user = await _user(db_session, user_id)
    assert (user.radius_km, user.notify_reminders) == (5, False)

    await handle_update(bot, _text(user_id, "/delete_me"))
    assert _sent(max_api)[-1]["text"] == texts.DELETE_CONFIRM
    await handle_update(bot, _callback(user_id, keyboards.CB_DELETE_YES))
    assert _sent(max_api)[-1]["text"] == texts.DELETE_DONE
    deleted = await db_session.get(User, user.id, populate_existing=True)
    assert deleted is not None
    assert deleted.deleted_at is not None and deleted.max_user_id is None


async def test_contact_confirms_phone(
    bot: BotContext,
    max_api: respx.MockRouter,
    db_app: FastAPI,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    import hashlib
    import hmac

    from tests.helpers import BOT_TOKEN, login_as
    from tests.test_orgs_api import INN

    user_id = random_max_id()
    headers, _ = await login_as(db_client, user_id, consents=("terms", "privacy", "org_pd"))
    org = (
        await db_client.post(
            "/api/v1/orgs", json={"name": "ДК Тестово", "kind": "dk"}, headers=headers
        )
    ).json()
    r = await db_client.post(
        f"/api/v1/orgs/{org['id']}/verification",
        json={"inn": INN, "site_url": "https://dk.test/"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    vcf = "BEGIN:VCARD\nTEL:+79120000000\nEND:VCARD"

    def contact(sign: str, owner: int) -> list[dict[str, Any]]:
        return [
            {
                "type": "contact",
                "payload": {"vcf_info": vcf, "hash": sign, "max_info": {"user_id": owner}},
            }
        ]

    good = hmac.new(BOT_TOKEN.encode(), vcf.encode(), hashlib.sha256).hexdigest()
    stranger = random_max_id()
    await handle_update(bot, _text(stranger, None, attachments=contact(good, stranger)))
    assert _sent(max_api)[-1]["text"] == texts.PHONE_NO_REQUEST
    await handle_update(bot, _text(user_id, None, attachments=contact("bad", user_id)))
    assert _sent(max_api)[-1]["text"] == texts.PHONE_BAD_SIGNATURE
    await handle_update(bot, _text(user_id, None, attachments=contact(good, user_id + 1)))
    assert _sent(max_api)[-1]["text"] == texts.PHONE_NOT_OWN
    await handle_update(bot, _text(user_id, None, attachments=contact(good, user_id)))
    assert _sent(max_api)[-1]["text"] == texts.PHONE_CONFIRMED

    status = (await db_client.get(f"/api/v1/orgs/{org['id']}/verification", headers=headers)).json()
    assert {s["code"]: s["status"] for s in status["steps"]}["phone"] == "ok"


async def test_queue_for_admin_only(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    await handle_update(bot, _text(random_max_id(), "/queue"))
    assert _sent(max_api)[-1]["text"] == texts.ADMIN_ONLY
    await handle_update(bot, _callback(random_max_id(), "adm:e:1:approve"))
    assert _answers(max_api)[-1]["notification"] == texts.ADMIN_ONLY

    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Очередь"), lat, lon)
    org = await make_org(db_session)
    approve = await make_event(db_session, locality, org=org, status="hidden", title="Скрытое")
    reject = await make_event(
        db_session, locality, trust_tier=TrustTier.community, status="pending", title="Ждёт"
    )
    await db_session.commit()

    await handle_update(bot, _text(777, "/queue"))
    assert any(m["text"].startswith("В очереди") for m in _sent(max_api))

    await handle_update(bot, _callback(777, f"adm:e:{approve.id}:approve"))
    assert _answers(max_api)[-1]["notification"] == texts.QUEUE_DONE_TOAST
    await handle_update(bot, _callback(777, f"adm:e:{approve.id}:approve"))
    assert _answers(max_api)[-1]["notification"] == texts.QUEUE_ALREADY_TOAST

    await handle_update(bot, _callback(777, f"adm:e:{reject.id}:reject"))
    assert _sent(max_api)[-1]["text"] == texts.QUEUE_ASK_REASON
    await handle_update(bot, _text(777, "нет"))
    assert _sent(max_api)[-1]["text"] == texts.QUEUE_REASON_TOO_SHORT
    await handle_update(bot, _text(777, "Это реклама, не событие"))
    assert _sent(max_api)[-1]["text"] == texts.QUEUE_DECIDED.format(
        id=reject.id, verdict=texts.QUEUE_VERDICTS["reject"]
    )

    await db_session.refresh(approve)
    await db_session.refresh(reject)
    assert approve.status == "published"
    assert reject.status == "rejected" and reject.moderation_reason == "Это реклама, не событие"


# --- Мастер «Добавить афишу», уведомления --------------------------------------------------


def _add_payloads(message: dict[str, Any]) -> list[str]:
    return [b["payload"] for b in _buttons(message) if b["type"] == "callback"]


async def test_add_wizard_step_by_step(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Мастерово"), lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, locality)
    title = _unique("Вечер песни ")

    await handle_update(bot, _text(user_id, "/add"))
    start = _sent(max_api)[-1]
    assert start["text"] == texts.ADD_START
    assert _add_payloads(start) == [keyboards.CB_ADD_STEPS, keyboards.CB_ADD_CANCEL]

    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_STEPS))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["title"]
    await handle_update(bot, _text(user_id, title))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["when"]
    # Непонятная дата — переспрашиваем тот же шаг.
    await handle_update(bot, _text(user_id, "когда-нибудь"))
    assert _sent(max_api)[-1]["text"].endswith(texts.ADD_ASK["when"])
    # «Назад» возвращает к названию, название уже заполнено — снова к дате.
    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_BACK))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["title"]
    await handle_update(bot, _text(user_id, title))
    await handle_update(bot, _text(user_id, "завтра в 19:00"))

    place = _sent(max_api)[-1]
    assert place["text"] == texts.ADD_ASK["place"]
    assert _add_payloads(place)[0] == f"add:loc:{locality.id}"
    await handle_update(bot, _callback(user_id, f"add:loc:{locality.id}"))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["venue"]
    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_SKIP))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["category"]
    await handle_update(bot, _callback(user_id, "add:cat:concert"))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["price"]
    await handle_update(bot, _callback(user_id, "add:price:free"))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["description"]
    await handle_update(bot, _text(user_id, "Поём под гитару всем селом, приходите с друзьями."))
    assert _sent(max_api)[-1]["text"] == texts.ADD_ASK["cover"]
    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_SKIP))

    preview = _sent(max_api)[-1]
    assert title in preview["text"] and locality.name in preview["text"]
    assert _add_payloads(preview)[0] == keyboards.CB_ADD_SEND
    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_SEND))

    done = _sent(max_api)[-1]
    assert done["text"] == texts.ADD_SENT_PENDING.format(title=title)
    assert await bot.states.get(user_id) == "idle"
    event = await db_session.scalar(
        select(Event).where(Event.title == title).execution_options(populate_existing=True)
    )
    assert event is not None
    assert event.trust_tier == TrustTier.community and event.status == "pending"
    assert event.category == "concert" and event.price_type == "free"
    assert event.locality_id == locality.id
    # Модерация — фоном в воркере (там же уведомление модераторам).
    assert isinstance(bot.jobs, MemoryJobQueue)
    assert ("moderate_event", (event.id,)) in [(j.name, j.args) for j in bot.jobs.jobs]
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.entity_type == "event", AuditLog.entity_id == event.id)
    )
    assert audit is not None


async def test_add_wizard_cancel_and_announcement(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, _unique("Отменино"), lat, lon)
    await db_session.commit()
    await db_session.refresh(locality)
    user_id = await _ready_user(bot, db_session, locality)
    title = _unique("Субботник ")

    # Анонс целиком: правила заполняют поля, дальше — первый незаполненный шаг.
    announce = f"{title}\n25.12 в 11:00 у клуба. Вход свободный, приходите всей семьёй!"
    await handle_update(bot, _text(user_id, "/add"))
    await handle_update(bot, _text(user_id, announce))
    parsed, step = _sent(max_api)[-2:]
    assert parsed["text"] == texts.ADD_PARSED
    assert await bot.states.get(user_id) != "idle"
    assert keyboards.CB_ADD_CANCEL in _add_payloads(step)

    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_CANCEL))
    assert _sent(max_api)[-1]["text"] == texts.ADD_CANCELLED
    assert await bot.states.get(user_id) == "idle"
    assert await bot.states.get_data(user_id) == {}
    assert await db_session.scalar(select(Event).where(Event.title == title)) is None
    # Кнопка мастера после отмены — не падаем, а говорим, что черновик устарел.
    await handle_update(bot, _callback(user_id, keyboards.CB_ADD_SEND))
    assert _sent(max_api)[-1]["text"] == texts.ADD_EXPIRED


async def test_add_requires_consent(bot: BotContext, max_api: respx.MockRouter) -> None:
    await handle_update(bot, _callback(random_max_id(), keyboards.CB_ADD))
    ask = _sent(max_api)[-1]
    assert ask["text"].startswith(texts.ADD_NEED_CONSENT)
    assert _buttons(ask)[0]["payload"] == keyboards.CB_CONSENT_ACCEPT


async def test_queued_messages_dedup_and_guests_skipped(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    jobs = MemoryJobQueue()
    queued = QueuedNotifier(jobs)
    await queued.send(1, "Твою афишу опубликовали", "ev_1")
    await queued.send(1, "Твою афишу опубликовали", "ev_1")
    await queued.send(1, "Твою афишу отклонили", "ev_1")
    ids = [j.job_id for j in jobs.jobs]
    # Повтор того же сообщения — тот же job_id: arq не поставит дубль.
    assert ids[0] == ids[1] != ids[2]
    assert all(j.name == "send_user_message" for j in jobs.jobs)

    guest = User(channel="web")
    db_session.add(guest)
    await db_session.commit()
    notifier = BotNotifier(bot.db, bot.max, "afisha_test_bot")
    await notifier.send(guest.id, "Решение по заявке", "ev_1")
    assert _sent(max_api) == []
