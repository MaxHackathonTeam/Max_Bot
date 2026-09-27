"""Небольшой Redis rate limiter для требований §14."""

import hashlib
import time
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, redis: Any, default_limit: int = 60) -> None:
        self.app = app
        self.redis = redis
        self.default_limit = default_limit

    def _rule(self, scope: Scope) -> tuple[int, int, str] | None:
        path, method = scope.get("path", ""), scope.get("method", "GET")
        if not path.startswith("/api/"):
            return None
        if path.endswith("/search/parse"):
            return 10, 60, "search"
        if method == "POST" and path == "/api/v1/events":
            return 10, 86400, "event-create"
        if method == "POST" and path == "/api/v1/auth/guest":
            return 5, 3600, "guest"
        if method == "POST" and path == "/api/v1/auth/web-code":
            return 10, 3600, "web-code"
        if path == "/api/v1/auth/web-code/poll":
            # Сайт опрашивает раз в 2–3 секунды, пока код живёт.
            return 60, 60, "web-code-poll"
        if path.endswith("/verification/recheck"):
            return 1, 600, "verification"
        return self.default_limit, 60, "api"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rule = self._rule(scope)
        if rule is None or scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        limit, window, bucket = rule
        headers = dict(scope.get("headers", []))
        forwarded = headers.get(b"x-forwarded-for", b"").decode().split(",")[-1].strip()
        client = forwarded or (scope.get("client") or ("unknown", 0))[0]
        identities = {"ip": client}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        if authorization.startswith("Bearer "):
            identities["user"] = authorization[7:]
        allowed = True
        if self.redis is not None:
            try:
                for identity, value in identities.items():
                    digest = hashlib.sha256(value.encode()).hexdigest()[:20]
                    key = f"rl:{bucket}:{identity}:{digest}:{int(time.time()) // window}"
                    count = int(await self.redis.incr(key))
                    if count == 1:
                        await self.redis.expire(key, window + 1)
                    allowed = allowed and count <= limit
            except Exception:
                # Лимитер не должен превращать недоступность Redis в отказ API.
                allowed = True
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Слишком много запросов, попробуй позже",
                        "details": {},
                    }
                },
                headers={"Retry-After": str(window)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
