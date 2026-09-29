"""Бот: «Об организаторе», афиши организации и поиск организаций (/orgs)."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import fsm, keyboards, texts
from app.bot.dispatcher import BotContext, handle_update
from app.bot.fsm import MemoryStateStore
from app.core.config import Settings
from app.integrations.max import MaxClient
from app.models.enums import OrgKind, TrustTier, VerificationStatus
from app.models.users import User
from app.services import users as users_service
from tests.factories import make_event, make_locality, make_org, random_area
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


def _answers(max_api: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(c.request.content) for c in max_api["answer"].calls]


def _buttons(message: dict[str, Any]) -> list[dict[str, Any]]:
    rows = message["attachments"][0]["payload"]["buttons"]
    return [button for row in rows for button in row]


def _by_text(message: dict[str, Any], text: str) -> dict[str, Any]:
    return next(b for b in _buttons(message) if b["text"] == text)


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


def _text(user_id: int, text: str) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "timestamp": 3,
        "message": {
            "sender": {"user_id": user_id, "first_name": "Маша"},
            "recipient": {"chat_id": 42, "chat_type": "dialog"},
            "body": {"mid": "m1", "text": text},
        },
    }


def _tomorrow(hours: int = 0) -> datetime:
    return datetime.now(UTC) + timedelta(days=1, hours=hours)


async def test_feed_org_button_profile_and_events(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, "Заречье", lat, lon)
    org = await make_org(db_session)
    org.name = "ДК «Заречье»"
    org.locality_id = locality.id
    org.description = "Дом культуры: хор, кружки и праздники."
    org.phone = "+79120000000"
    org.inn = "7701234560"
    for i in range(7):
        await make_event(
            db_session,
            locality,
            title=f"Концерт {i}",
            org=org,
            starts=[_tomorrow(i)],
            pushkin_card=True,
        )
    await make_event(
        db_session,
        locality,
        title="Соседский сход",
        org=org,
        trust_tier=TrustTier.community,
        starts=[_tomorrow(3)],
    )
    await db_session.commit()
    user_id = random_max_id()
    await handle_update(bot, _callback(user_id, keyboards.CB_CONSENT_ACCEPT))
    user = await db_session.scalar(select(User).where(User.max_user_id == user_id))
    assert user is not None
    await users_service.set_location(db_session, user, locality.id)

    await handle_update(bot, _callback(user_id, keyboards.CB_PUSHKIN))
    feed = _sent(max_api)[-1]
    about = [b for b in _buttons(feed) if b["text"] == texts.ORG_ABOUT_BUTTON]
    assert about and all(b["payload"] == f"orgp:{org.id}" for b in about)

    await handle_update(bot, _callback(user_id, about[0]["payload"]))
    profile = _sent(max_api)[-1]
    assert profile["text"].startswith("🏛 ДК «Заречье»\n" + texts.ORG_PROFILE_VERIFIED)
    assert "Заречье · Дом культуры" in profile["text"]
    assert "О нас:\nДом культуры: хор, кружки и праздники." in profile["text"]
    assert texts.ORG_PROFILE_EVENTS.format(count=8) in profile["text"]
    for secret in ("+79120000000", "7701234560"):
        assert secret not in profile["text"]
    # PUBLIC_BASE_URL в тестах не https — «Открыть на сайте» ведёт в мини-приложение.
    site = _by_text(profile, texts.ORG_SITE_BUTTON)
    assert site["type"] == "open_app" and site["payload"] == f"org_{org.id}"
    community = _by_text(profile, texts.ORG_COMMUNITY_BUTTON.format(count=1))
    events = _by_text(profile, texts.ORG_EVENTS_BUTTON.format(count=7))
    assert events["payload"] == f"orgp:ev:{org.id}:o:0"

    await handle_update(bot, _callback(user_id, events["payload"]))
    first = _sent(max_api)[-1]
    assert texts.ORG_EVENTS_TITLE.format(name="ДК «Заречье»") in first["text"]
    assert "Концерт 0" in first["text"] and "Концерт 5" not in first["text"]
    assert "Соседский сход" not in first["text"]
    more = _by_text(first, texts.FEED_MORE_BUTTON)
    assert more["payload"].startswith(f"orgp:ev:{org.id}:o:5:")
    assert all(len(b.get("payload", "")) <= 1024 for b in _buttons(first))
    assert _by_text(first, texts.ORG_BACK_BUTTON)["payload"] == f"orgp:{org.id}"

    await handle_update(bot, _callback(user_id, more["payload"]))
    second = _sent(max_api)[-1]
    assert "6. " in second["text"] and "Концерт 6" in second["text"]
    assert not any(b["text"] == texts.FEED_MORE_BUTTON for b in _buttons(second))

    # Ленты не смешиваются: «От сообщества» — отдельным сообщением.
    await handle_update(bot, _callback(user_id, community["payload"]))
    other = _sent(max_api)[-1]
    assert "Соседский сход" in other["text"] and "Концерт" not in other["text"]
    assert other["text"].startswith(texts.FEED_TIERS["community"])


async def test_org_search_by_command_and_state(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    tag = uuid.uuid4().hex[:8]
    lat, lon = random_area()
    locality = await make_locality(db_session, "Лесное", lat, lon)
    found = await make_org(db_session)
    found.name = f"Библиотека Звездочёт {tag}"
    found.kind = OrgKind.library
    found.locality_id = locality.id
    hidden = await make_org(db_session)
    hidden.name = f"Библиотека Звездочёт {tag} отозванная"
    hidden.verification_status = VerificationStatus.revoked
    await db_session.commit()
    user_id = random_max_id()

    await handle_update(bot, _text(user_id, "/orgs"))
    assert _sent(max_api)[-1]["text"] == texts.ORG_SEARCH_PROMPT
    assert await bot.states.get(user_id) == fsm.ORG_SEARCH

    await handle_update(bot, _text(user_id, "б"))
    assert _sent(max_api)[-1]["text"] == texts.ORG_SEARCH_SHORT.format(min=2)
    assert await bot.states.get(user_id) == fsm.ORG_SEARCH

    # Опечатка «звездочет» — нечёткий поиск тем же сервисом, что и API.
    await handle_update(bot, _text(user_id, f"звездочет {tag}"))
    results = _sent(max_api)[-1]
    assert results["text"] == texts.ORG_SEARCH_RESULTS
    assert await bot.states.get(user_id) == fsm.IDLE
    options = [b for b in _buttons(results) if b["payload"].removeprefix("orgp:").isdigit()]
    assert [b["payload"] for b in options] == [f"orgp:{found.id}"]
    assert options[0]["text"] == f"✅ Библиотека Звездочёт {tag} · Лесное"

    await handle_update(bot, _callback(user_id, options[0]["payload"]))
    profile = _sent(max_api)[-1]
    assert profile["text"].startswith(f"🏛 Библиотека Звездочёт {tag}")
    assert texts.ORG_PROFILE_NO_EVENTS.strip() in profile["text"]

    # Отозванная организация скрыта и по старой кнопке.
    await handle_update(bot, _callback(user_id, f"orgp:{hidden.id}"))
    assert _answers(max_api)[-1] == {"notification": texts.ORG_NOT_FOUND_TOAST}

    await handle_update(bot, _text(user_id, f"/orgs нетакойорганизации{tag}"))
    empty = _sent(max_api)[-1]
    assert empty["text"] == texts.ORG_SEARCH_EMPTY.format(query=f"нетакойорганизации{tag}")
    assert _by_text(empty, texts.ORG_SEARCH_AGAIN_BUTTON)["payload"] == keyboards.CB_ORG_FIND

    await handle_update(bot, _callback(user_id, keyboards.CB_ORG_FIND))
    assert _sent(max_api)[-1]["text"] == texts.ORG_SEARCH_PROMPT

    await handle_update(bot, _callback(user_id, "orgp:ev:1:x:0"))
    assert _answers(max_api)[-1] == {"notification": texts.FEED_EXPIRED_TOAST}
    await handle_update(bot, _callback(user_id, f"orgp:ev:{found.id}:o:0:мусор"))
    assert _answers(max_api)[-1] == {"notification": texts.FEED_EXPIRED_TOAST}


async def test_org_menu_has_search(bot: BotContext, max_api: respx.MockRouter) -> None:
    user_id = random_max_id()
    await handle_update(bot, _text(user_id, "/org"))
    menu = _sent(max_api)[-1]
    assert _by_text(menu, texts.ORG_SEARCH_BUTTON)["payload"] == keyboards.CB_ORG_FIND
