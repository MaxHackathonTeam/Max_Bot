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


class FakeLlm:
    """LlmClient для тестов: отдаёт ответы по очереди (последний — повторно)."""

    model = "fake-llm"

    def __init__(self, *answers: str, fail: bool = False) -> None:
        self.answers = list(answers)
        self.fail = fail
        self.calls = 0

    async def chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 600
    ) -> Any:
        from app.integrations.gigachat.client import ChatResult, LlmUnavailable

        self.calls += 1
        if self.fail:
            raise LlmUnavailable("down")
        text = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return ChatResult(text=text, tokens_in=10, tokens_out=10, model=self.model)


def verdict(verdict: str, confidence: float = 0.95, *categories: str) -> str:
    return json.dumps(
        {"verdict": verdict, "confidence": confidence, "categories": list(categories)}
    )
