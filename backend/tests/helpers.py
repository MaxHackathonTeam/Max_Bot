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


async def login_as(
    client: httpx.AsyncClient,
    max_id: int | None = None,
    *,
    consents: tuple[str, ...] = ("terms", "privacy"),
    first_name: str = "Тест",
) -> tuple[dict[str, str], dict[str, Any]]:
    """Вход под заданным MAX id (например, админом из ADMIN_MAX_USER_IDS)."""
    raw = make_init_data({"id": max_id or random_max_id(), "first_name": first_name})
    r = await client.post("/api/v1/auth/max", json={"init_data": raw})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    if consents:
        r = await client.post("/api/v1/me/consents", json={"docs": list(consents)}, headers=headers)
        assert r.status_code == 200, r.text
    return headers, body["user"]


class FakeRedis:
    """Минимум redis.asyncio для кодов входа: get/set(ex, nx, xx, keepttl)/delete, без TTL."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool:
        if (nx and key in self.data) or (xx and key not in self.data):
            return False
        self.data[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        return sum(self.data.pop(k, None) is not None for k in keys)
