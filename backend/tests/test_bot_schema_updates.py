"""Обновления MAX в форме из api-schema (schema.yaml: BotStartedUpdate, MessageCreatedUpdate,
MessageCallbackUpdate) проходят всю цепочку: /bot/webhook → очередь → воркер → ответ в MAX."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from structlog.testing import capture_logs

from app.bot import keyboards, texts
from app.bot.dispatcher import BotContext
from app.bot.fsm import MemoryStateStore
from app.core.config import Settings
from app.integrations.max import MaxClient
from app.workers.settings import process_bot_update
from tests.helpers import WEBHOOK_SECRET, random_max_id

BASE = "https://max.test"
HEADERS = {"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}


def _user(user_id: int) -> dict[str, Any]:
    # User: required user_id, first_name, is_bot.
    return {
        "user_id": user_id,
        "first_name": "Маша",
        "last_name": None,
        "username": None,
        "is_bot": False,
        "last_activity_time": 1758650000000,
    }


def bot_started(user_id: int) -> dict[str, Any]:
    # BotStartedUpdate: required update_type, timestamp, chat_id, user.
    return {
        "update_type": "bot_started",
        "timestamp": 1758650000000,
        "chat_id": 9000 + user_id % 1000,
        "user": _user(user_id),
        "payload": None,
        "user_locale": "ru",
    }


def message_created(user_id: int, text: str) -> dict[str, Any]:
    # MessageCreatedUpdate.message: Message (required recipient, body, timestamp);
    # Recipient: required chat_type; MessageBody: required mid, seq.
    return {
        "update_type": "message_created",
        "timestamp": 1758650001000,
        "message": {
            "sender": _user(user_id),
            "recipient": {"chat_id": 9000 + user_id % 1000, "chat_type": "dialog", "user_id": None},
            "timestamp": 1758650001000,
            "body": {"mid": f"mid.{user_id}.1", "seq": 1, "text": text, "attachments": None},
            "stat": None,
            "url": None,
        },
        "user_locale": "ru",
    }


def message_callback(user_id: int, payload: str) -> dict[str, Any]:
    # MessageCallbackUpdate: required callback (Callback: timestamp, callback_id, user);
    # message — исходное сообщение с клавиатурой, может быть null.
    return {
        "update_type": "message_callback",
        "timestamp": 1758650002000,
        "callback": {
            "timestamp": 1758650002000,
            "callback_id": f"cb.{user_id}",
            "payload": payload,
            "user": _user(user_id),
        },
        "message": {
            "sender": {"user_id": 1, "first_name": "Афиша", "is_bot": True},
            "recipient": {"chat_id": 9000 + user_id % 1000, "chat_type": "dialog"},
            "timestamp": 1758650000500,
            "body": {"mid": "mid.bot.1", "seq": 1, "text": "меню", "attachments": []},
        },
        "user_locale": "ru",
    }


class Sink:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def put(self, update: dict[str, Any]) -> None:
        self.updates.append(update)

    async def close(self) -> None:
        return None


@pytest.fixture
def max_api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/messages", name="send").respond(
            200, json={"message": {"body": {"mid": "mid.out", "seq": 1}}}
        )
        mock.post("/answers", name="answer").respond(200, json={"success": True})
        yield mock


async def _deliver(db_app: FastAPI, db_settings: Settings, update: dict[str, Any]) -> None:
    """Как в проде: POST от MAX на webhook, затем задача process_bot_update в воркере."""
    sink = Sink()
    db_app.state.update_sink = sink
    transport = httpx.ASGITransport(app=db_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/bot/webhook", json=update, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert sink.updates == [update]
    bot = BotContext(
        settings=db_settings,
        db=db_app.state.db,
        max=MaxClient("tkn", BASE, retries=0, backoff_s=0),
        states=MemoryStateStore(),
    )
    await process_bot_update({"bot": bot}, sink.updates[0])


def _sent(max_api: respx.MockRouter) -> list[dict[str, Any]]:
    return [json.loads(c.request.content) for c in max_api["send"].calls]


async def test_start_from_schema_gets_reply(
    db_app: FastAPI, db_settings: Settings, max_api: respx.MockRouter
) -> None:
    await _deliver(db_app, db_settings, bot_started(random_max_id()))
    sent = _sent(max_api)
    assert sent and sent[0]["text"].startswith("Привет, Маша!")
    assert max_api["send"].calls[0].request.url.params.get("chat_id")


async def test_text_from_schema_gets_reply(
    db_app: FastAPI, db_settings: Settings, max_api: respx.MockRouter
) -> None:
    await _deliver(db_app, db_settings, message_created(random_max_id(), "/help"))
    assert _sent(max_api)[0]["text"] == texts.HELP


async def test_whoami_shows_id(
    db_app: FastAPI, db_settings: Settings, max_api: respx.MockRouter
) -> None:
    user_id = random_max_id()
    await _deliver(db_app, db_settings, message_created(user_id, "/whoami"))
    reply = _sent(max_api)[0]["text"]
    assert str(user_id) in reply and texts.MYID_USER in reply


async def test_callback_from_schema_gets_answer(
    db_app: FastAPI, db_settings: Settings, max_api: respx.MockRouter
) -> None:
    await _deliver(db_app, db_settings, message_callback(random_max_id(), keyboards.CB_MENU))
    # На нажатие кнопки бот обязательно отвечает (POST /answers), иначе у кнопки крутится часик.
    assert max_api["answer"].called or max_api["send"].called


async def test_callback_empty_answer_rejected_is_not_an_error(
    db_app: FastAPI, db_settings: Settings, max_api: respx.MockRouter
) -> None:
    """Прод: MAX отвечает 400 на пустой POST /answers — не показываем «Что-то пошло не так»."""
    max_api.post("/answers", name="answer").mock(
        side_effect=lambda r: httpx.Response(
            200 if json.loads(r.content) else 400,
            json={"success": True} if json.loads(r.content) else {"code": "proto.payload"},
        )
    )
    await _deliver(db_app, db_settings, message_callback(random_max_id(), keyboards.CB_MENU))
    answers = [json.loads(c.request.content) for c in max_api["answer"].calls]
    assert {"notification": texts.ERROR} not in answers
    sent = _sent(max_api)
    assert sent and all(m["text"] != texts.ERROR for m in sent)


class BrokenSink(Sink):
    async def put(self, update: dict[str, Any]) -> None:
        raise ConnectionError("redis down")


async def test_webhook_enqueue_failure_is_logged(db_app: FastAPI) -> None:
    db_app.state.update_sink = BrokenSink()
    transport = httpx.ASGITransport(app=db_app, raise_app_exceptions=False)
    update = message_created(random_max_id(), "Привет, мой телефон +79990000000")
    with capture_logs() as logs:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/bot/webhook", json=update, headers=HEADERS)
    assert r.status_code == 503
    failed = [e for e in logs if e["event"] == "bot_webhook_enqueue_failed"]
    assert failed and failed[0]["update_type"] == "message_created"
    assert "7999" not in json.dumps(logs, ensure_ascii=False, default=str)
