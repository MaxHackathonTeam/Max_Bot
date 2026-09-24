"""Сценарии бота (§12) на настоящей БД; API MAX подменён respx."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards, texts
from app.bot.dispatcher import BotContext, handle_update, parse_start_payload
from app.core.config import Settings
from app.integrations.max import MaxClient
from app.services import users as users_service
from tests.helpers import random_max_id

BASE = "https://max.test"


@pytest.fixture
def bot(db_app: FastAPI, db_settings: Settings) -> BotContext:
    client = MaxClient("tkn", BASE, retries=0, backoff_s=0)
    return BotContext(settings=db_settings, db=db_app.state.db, max=client)


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


def _text(user_id: int, text: str, chat_type: str = "dialog") -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "timestamp": 3,
        "message": {
            "sender": {"user_id": user_id, "first_name": "Маша"},
            "recipient": {"chat_id": 42, "chat_type": chat_type},
            "body": {"mid": "m1", "text": text},
        },
    }


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


async def test_start_asks_consent_and_shows_menu(
    bot: BotContext, max_api: respx.MockRouter, db_session: AsyncSession
) -> None:
    user_id = random_max_id()
    await handle_update(bot, _started(user_id))

    greeting, consent, menu = _sent(max_api)
    assert greeting["text"].startswith("Привет, Маша!")
    assert "/legal/terms" in consent["text"]
    assert _buttons(consent)[0]["payload"] == keyboards.CB_CONSENT_ACCEPT
    assert _buttons(menu)[0] == {
        "type": "open_app",
        "text": texts.MENU_OPEN_APP,
        "web_app": "afisha_test_bot",
    }
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
    assert _sent(max_api)[-1]["text"] == texts.MENU

    user = await users_service.get_by_max_id(db_session, user_id)
    assert user is not None
    assert await users_service.has_required_consents(db_session, user)

    # После согласия /start сразу показывает меню без повторного запроса.
    before = len(_sent(max_api))
    await handle_update(bot, _text(user_id, "/start"))
    (menu,) = _sent(max_api)[before:]
    assert menu["text"].startswith("Привет, Маша!")
    assert _buttons(menu)[0]["type"] == "open_app"


async def test_soon_callback_toast(bot: BotContext, max_api: respx.MockRouter) -> None:
    await handle_update(bot, _callback(random_max_id(), keyboards.CB_TODAY))
    answer = json.loads(max_api["answer"].calls.last.request.content)
    assert answer == {"notification": texts.SOON_TOAST}
    assert _sent(max_api) == []


async def test_help_and_unknown_text(bot: BotContext, max_api: respx.MockRouter) -> None:
    user_id = random_max_id()
    await handle_update(bot, _text(user_id, "/help"))
    await handle_update(bot, _text(user_id, "где концерт?"))
    help_msg, unknown = _sent(max_api)
    assert help_msg["text"] == texts.HELP
    assert unknown["text"] == texts.UNKNOWN_TEXT


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
