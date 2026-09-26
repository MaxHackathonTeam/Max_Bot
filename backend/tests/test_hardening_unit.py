"""Unit coverage for stage 6 security middleware and log redaction."""

import json

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core.logging import mask_pii
from app.core.rate_limit import RateLimitMiddleware


class FakeRedis:
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.counts = counts or {}
        self.expirations: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations.append((key, ttl))


@pytest.mark.asyncio
async def test_rate_limit_checks_ip_and_bearer_identity() -> None:
    responses: list[Message] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    redis = FakeRedis()
    middleware = RateLimitMiddleware(downstream, redis=redis, default_limit=1)
    scope: Scope = {
        "type": "http",
        "path": "/api/v1/events",
        "method": "GET",
        "headers": [(b"authorization", b"Bearer sample-jwt"), (b"x-forwarded-for", b"192.0.2.1")],
        "client": ("127.0.0.1", 1234),
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        responses.append(message)

    await middleware(scope, receive, send)
    assert responses[0]["status"] == 200
    assert len(redis.counts) == 2
    assert len(redis.expirations) == 2

    responses.clear()
    await middleware(scope, receive, send)
    assert responses[0]["status"] == 429
    assert b"retry-after" in dict(responses[0]["headers"])


def test_rate_limit_rules_match_stage6_policy() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        return None

    middleware = RateLimitMiddleware(downstream, redis=None)
    assert middleware._rule({"path": "/api/v1/search/parse", "method": "POST"}) == (
        10,
        60,
        "search",
    )
    assert middleware._rule({"path": "/api/v1/events", "method": "POST"}) == (
        10,
        86400,
        "event-create",
    )
    assert middleware._rule({"path": "/api/v1/orgs/1/verification/recheck", "method": "POST"}) == (
        1,
        600,
        "verification",
    )


def test_log_processor_redacts_pii_and_secrets() -> None:
    result = mask_pii(None, "event", {"phone": "+7 999 123-45-67", "access_token": "secret"})
    assert json.dumps(result) == '{"phone": "[REDACTED]", "access_token": "[REDACTED]"}'
