from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.bot.queue import update_job_id
from app.core.config import Settings
from app.main import create_app
from tests.helpers import WEBHOOK_SECRET

UPDATE = {
    "update_type": "message_created",
    "timestamp": 1758650000000,
    "message": {"body": {"mid": "mid.1", "text": "/start"}},
}


class FakeSink:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def put(self, update: dict[str, Any]) -> None:
        self.updates.append(update)

    async def close(self) -> None:
        return None


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


async def _client(secret: str | None, sink: FakeSink) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,
        env="test",
        max_webhook_secret=SecretStr(secret) if secret else None,
    )
    app = create_app(settings)
    app.state.update_sink = sink
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def wh_client(sink: FakeSink) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(WEBHOOK_SECRET, sink):
        yield c


@pytest.mark.parametrize("headers", [{}, {"X-Max-Bot-Api-Secret": "wrong"}])
async def test_wrong_secret_401(
    wh_client: httpx.AsyncClient, sink: FakeSink, headers: dict[str, str]
) -> None:
    r = await wh_client.post("/bot/webhook", json=UPDATE, headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert sink.updates == []


async def test_wrong_secret_401_even_with_bad_body(wh_client: httpx.AsyncClient) -> None:
    r = await wh_client.post(
        "/bot/webhook", content=b"not json", headers={"X-Max-Bot-Api-Secret": "wrong"}
    )
    assert r.status_code == 401


async def test_no_secret_configured_401(sink: FakeSink) -> None:
    async for c in _client(None, sink):
        r = await c.post("/bot/webhook", json=UPDATE, headers={"X-Max-Bot-Api-Secret": "x"})
        assert r.status_code == 401


async def test_valid_secret_enqueues(wh_client: httpx.AsyncClient, sink: FakeSink) -> None:
    r = await wh_client.post(
        "/bot/webhook", json=UPDATE, headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert sink.updates == [UPDATE]


async def test_bad_body_400(wh_client: httpx.AsyncClient) -> None:
    headers = {"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}
    r = await wh_client.post("/bot/webhook", content=b"[1]", headers=headers)
    assert r.status_code == 400


def test_update_job_id_dedupes() -> None:
    assert update_job_id(UPDATE) == "bot:message_created:1758650000000:mid.1"
    callback = {"update_type": "message_callback", "timestamp": 1, "callback": {"callback_id": "c"}}
    assert update_job_id(callback) == "bot:message_callback:1:c"


def test_prod_webhook_requires_secret() -> None:
    with pytest.raises(ValueError, match="MAX_WEBHOOK_SECRET"):
        Settings(
            _env_file=None,
            env="prod",
            jwt_secret=SecretStr("x" * 40),
            bot_mode="webhook",
        )
