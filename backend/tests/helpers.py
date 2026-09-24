"""Общие константы и генераторы тестовых данных."""

import json
import random
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.security import sign

BOT_TOKEN = "test_bot_token_123"
JWT_SECRET = "test-jwt-secret-" + "x" * 32
WEBHOOK_SECRET = "test_webhook_secret"


def random_max_id() -> int:
    return random.randint(10**9, 10**12)


def make_init_data(
    user: dict[str, Any],
    *,
    token: str = BOT_TOKEN,
    auth_date: int | None = None,
    **extra: str,
) -> str:
    params = {
        "user": json.dumps(user, ensure_ascii=False, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        **extra,
    }
    params["hash"] = sign(params, token)
    return urlencode(params)


async def login(
    client: httpx.AsyncClient, *, consents: bool = True, first_name: str = "Тест"
) -> tuple[dict[str, str], dict[str, Any]]:
    """Вход через initData; возвращает заголовки с токеном и профиль."""
    raw = make_init_data({"id": random_max_id(), "first_name": first_name})
    r = await client.post("/api/v1/auth/max", json={"init_data": raw})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    if consents:
        r = await client.post(
            "/api/v1/me/consents", json={"docs": ["terms", "privacy"]}, headers=headers
        )
        assert r.status_code == 200, r.text
    return headers, body["user"]
