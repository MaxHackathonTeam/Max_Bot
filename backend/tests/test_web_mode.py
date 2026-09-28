"""Сайт без MAX: публичное чтение, гость, вход по коду из бота, перенос данных гостя."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.dispatcher import BotContext, handle_update
from app.bot.fsm import MemoryStateStore
from app.bot.notify import BotNotifier
from app.core.config import Settings
from app.integrations.max import MaxClient
from app.models.events import SavedSession
from app.models.system import AuditLog
from app.models.users import User
from app.services import drafts, search_parse, web_login
from tests.factories import make_event, make_locality, random_area
from tests.helpers import login, random_max_id

BASE = "https://max.test"
WEDNESDAY = datetime(2026, 9, 30, 9, tzinfo=UTC)


@pytest.fixture
def bot(db_app: FastAPI, db_settings: Settings) -> BotContext:
    client = MaxClient("tkn", BASE, retries=0, backoff_s=0)
    return BotContext(
        settings=db_settings,
        db=db_app.state.db,
        max=client,
        states=MemoryStateStore(),
        redis=db_app.state.redis,
    )


@pytest.fixture
def max_api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/messages", name="send").respond(200, json={"message": {}})
        mock.post("/answers", name="answer").respond(200, json={"success": True})
        yield mock


def _last(max_api: respx.MockRouter, route: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(max_api[route].calls.last.request.content)
    return body


def _started(user_id: int, payload: str) -> dict[str, Any]:
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


async def _guest(client: httpx.AsyncClient) -> tuple[dict[str, str], dict[str, Any]]:
    r = await client.post("/api/v1/auth/guest")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert body["user"]["max_user_id"] is None
    assert body["user"]["channel"] == "web"
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires - datetime.now(UTC) > timedelta(days=29)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r = await client.post(
        "/api/v1/me/consents", json={"docs": ["terms", "privacy"]}, headers=headers
    )
    assert r.status_code == 200, r.text
    return headers, body["user"]


async def test_public_reads_without_token(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, "Публичное", lat, lon)
    await make_event(db_session, locality, title="Концерт для всех")
    await db_session.commit()

    feed = await db_client.get("/api/v1/events", params={"locality_id": locality.id})
    assert feed.status_code == 200 and feed.json()["items"]
    near = await db_client.get("/api/v1/localities/nearest", params={"lat": lat, "lon": lon})
    assert near.status_code == 200, near.text
    assert (await db_client.get(f"/api/v1/localities/{locality.id}")).status_code == 200
    assert (await db_client.get("/api/v1/categories")).status_code == 200
    parsed = await db_client.post("/api/v1/search/parse", json={"text": "бесплатно в выходные"})
    assert parsed.status_code == 200, parsed.text
    assert parsed.json()["free"] is True
    assert parsed.json()["date"] == "weekend"
    # Запись без токена — 401 в общем формате ошибок.
    r = await db_client.post(f"/api/v1/events/{feed.json()['items'][0]['id']}/save")
    assert r.status_code == 401 and r.json()["error"]["message"]


async def test_guest_can_save(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    lat, lon = random_area()
    event = await make_event(db_session, await make_locality(db_session, "Гостевое", lat, lon))
    await db_session.commit()
    headers, me = await _guest(db_client)
    r = await db_client.post(f"/api/v1/events/{event.id}/save", headers=headers)
    assert r.status_code == 200 and r.json()["saved_session_ids"]
    assert (await db_client.get("/api/v1/me", headers=headers)).json()["id"] == me["id"]
    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "user.create", AuditLog.entity_id == me["id"])
    )
    assert audit is not None and audit.diff == {"source": "web_guest"}


async def test_web_login_merges_guest(
    bot: BotContext,
    max_api: respx.MockRouter,
    db_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    lat, lon = random_area()
    event = await make_event(db_session, await make_locality(db_session, "Входное", lat, lon))
    await db_session.commit()
    guest_headers, guest = await _guest(db_client)
    await db_client.post(f"/api/v1/events/{event.id}/save", headers=guest_headers)

    r = await db_client.post("/api/v1/auth/web-code", headers=guest_headers)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert r.json()["expires_in"] == 300
    assert r.json()["deeplink"] == f"https://max.ru/afisha_test_bot?start=login_{code}"
    poll = {"code": code}
    pending = await db_client.post("/api/v1/auth/web-code/poll", json=poll)
    assert pending.status_code == 202 and pending.json() == {"status": "pending"}

    max_id = random_max_id()
    await handle_update(bot, _started(max_id, f"login_{code}"))
    prompt = _last(max_api, "send")
    assert prompt["text"] == texts.WEB_LOGIN_CONFIRM.format(name="Маша", code=code)
    button = prompt["attachments"][0]["payload"]["buttons"][0][0]
    assert button["payload"] == f"{keyboards.P_WEB_LOGIN}:{code}"
    await handle_update(bot, _callback(max_id, button["payload"]))
    assert _last(max_api, "answer")["notification"] == texts.WEB_LOGIN_DONE_TOAST

    done = await db_client.post("/api/v1/auth/web-code/poll", json=poll)
    assert done.status_code == 200, done.text
    me = done.json()["user"]
    assert me["max_user_id"] == max_id and me["channel"] == "max"
    # Код одноразовый.
    again = await db_client.post("/api/v1/auth/web-code/poll", json=poll)
    assert again.status_code == 410 and again.json()["error"]["code"] == "code_expired"

    saved = await db_session.scalar(
        select(func.count()).select_from(SavedSession).where(SavedSession.user_id == me["id"])
    )
    assert saved == 1
    old = await db_session.get(User, guest["id"], populate_existing=True)
    assert old is not None and old.deleted_at is not None
    merged = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "user.merge_guest", AuditLog.entity_id == me["id"]
        )
    )
    assert merged is not None and merged.diff is not None
    assert merged.diff["guest_user_id"] == guest["id"]


async def test_web_login_unknown_code(
    bot: BotContext, max_api: respx.MockRouter, db_client: httpx.AsyncClient
) -> None:
    r = await db_client.post("/api/v1/auth/web-code/poll", json={"code": "ZZZZZZ"})
    assert r.status_code == 410 and r.json()["error"]["message"]
    await handle_update(bot, _callback(random_max_id(), f"{keyboards.P_WEB_LOGIN}:ZZZZZZ"))
    assert _last(max_api, "send")["text"] == texts.WEB_LOGIN_EXPIRED


def test_code_from_start() -> None:
    assert web_login.code_from_start("login_abc234") == "ABC234"
    assert web_login.code_from_start("/start login_ABC234") == "ABC234"
    assert web_login.code_from_start("login_ABC") is None
    assert web_login.code_from_start("ev_12") is None
    assert web_login.code_from_start(None) is None


async def test_notifications_skip_guests(
    db_app: FastAPI, db_client: httpx.AsyncClient, max_api: respx.MockRouter
) -> None:
    _, guest = await _guest(db_client)
    notifier = BotNotifier(db_app.state.db, MaxClient("tkn", BASE, retries=0, backoff_s=0), None)
    assert await notifier.send_raw(guest["id"], "Напоминание") is False
    assert not max_api["send"].called


async def test_search_parse_rules(db_session: AsyncSession) -> None:
    lat, lon = random_area()
    await make_locality(db_session, "Старая Русса", lat, lon)
    await db_session.commit()
    parsed = await search_parse.parse(
        db_session, "концерты в Старой Руссе до 500 рублей после 18", now=WEDNESDAY
    )
    assert parsed.categories == ("concert",)
    assert parsed.locality_name == "Старая Русса"
    assert parsed.price_max == 500 and parsed.time_from == 18
    assert not parsed.fallback

    weekend = await search_parse.parse(db_session, "бесплатно в выходные", now=WEDNESDAY)
    assert weekend.free and weekend.date == "weekend"
    unknown = await search_parse.parse(db_session, "фыва пролд", now=WEDNESDAY)
    assert unknown.fallback and unknown.q == "фыва пролд"


async def test_draft_from_text(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    _, me = await login(db_client)
    user = await db_session.get(User, me["id"])
    assert user is not None
    text = (
        "Концерт народного хора\n"
        "15 октября в 18:00, вход свободный. Принимаем Пушкинскую карту.\n"
        "Подробности: https://example.org/concert"
    )
    event = await drafts.create_from_text(db_session, user, text, None)
    assert event.title == "Концерт народного хора"
    assert event.category == "concert"
    assert event.pushkin_card is True
    assert {"title", "category", "pushkin_card"} <= set(event.ai_fields or [])
