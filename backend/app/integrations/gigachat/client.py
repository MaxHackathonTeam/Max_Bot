"""Клиент GigaChat (§8): OAuth с кэшем токена в Redis, chat/completions.

- OAuth: POST GIGACHAT_OAUTH_URL, `Authorization: Basic <GIGACHAT_AUTH_KEY>`, заголовок RqUID,
  тело `scope=GIGACHAT_API_PERS` → {access_token, expires_at (мс)}. Токен живёт 30 мин.
- Кэш токена в Redis до expires_at − 60 с; получение нового — под single-flight lock
  (процессный asyncio.Lock + Redis-lock между процессами).
- Чат: POST {GIGACHAT_API_URL}/chat/completions → choices[0].message.content, usage.
- TLS: сертификат НУЦ Минцифры из GIGACHAT_CA_BUNDLE поверх системного хранилища.
Адреса берутся из env — сверить с developers.sber.ru перед запуском.
"""

import asyncio
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import structlog
from redis.asyncio import Redis

from app.core.config import Settings
from app.integrations.http import ExternalApiError, request_json

log = structlog.get_logger(__name__)

TOKEN_KEY = "gigachat:token"  # noqa: S105 — ключ Redis, не секрет
LOCK_KEY = "gigachat:token:lock"
REFRESH_BEFORE_S = 60
TIMEOUT_S = 20.0


class LlmUnavailable(Exception):
    """LLM недоступна: нет ключа, сеть, 5xx, бюджет — вызывающий берёт fallback."""


@dataclass(frozen=True)
class ChatResult:
    text: str
    tokens_in: int | None
    tokens_out: int | None
    model: str


class LlmClient(Protocol):
    model: str

    async def chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 600
    ) -> ChatResult: ...


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext | bool:
    if not ca_bundle:
        return True
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=ca_bundle)
    return context


class GigaChatClient:
    def __init__(
        self,
        *,
        auth_key: str,
        scope: str,
        oauth_url: str,
        api_url: str,
        model: str,
        redis: Redis,
        ca_bundle: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._auth_key = auth_key
        self._scope = scope
        self._oauth_url = oauth_url
        self._api_url = api_url.rstrip("/")
        self._redis = redis
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            timeout=TIMEOUT_S, verify=_ssl_context(ca_bundle), transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _cached_token(self) -> str | None:
        value = await self._redis.get(TOKEN_KEY)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def _fetch_token(self) -> str:
        try:
            data = await request_json(
                self._http,
                "gigachat_oauth",
                "POST",
                self._oauth_url,
                headers={
                    "Authorization": f"Basic {self._auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Accept": "application/json",
                },
                data={"scope": self._scope},
            )
        except ExternalApiError as exc:
            raise LlmUnavailable(str(exc)) from exc
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise LlmUnavailable("OAuth без access_token")
        expires_ms = data.get("expires_at")
        expires_s = expires_ms / 1000 if isinstance(expires_ms, int | float) else time.time() + 1800
        ttl = int(expires_s - time.time() - REFRESH_BEFORE_S)
        if ttl > 0:
            await self._redis.set(TOKEN_KEY, token, ex=ttl)
        return token

    async def _token(self) -> str:
        token = await self._cached_token()
        if token:
            return token
        async with self._lock, self._redis.lock(LOCK_KEY, timeout=15, blocking_timeout=15):
            # Пока ждали лок, токен мог получить другой процесс.
            token = await self._cached_token()
            return token or await self._fetch_token()

    async def chat(
        self, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 600
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(2):
            token = await self._token()
            try:
                data = await request_json(
                    self._http,
                    "gigachat",
                    "POST",
                    f"{self._api_url}/chat/completions",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    json=body,
                )
            except ExternalApiError as exc:
                if exc.status_code == 401 and attempt == 0:
                    await self._redis.delete(TOKEN_KEY)
                    continue
                raise LlmUnavailable(str(exc)) from exc
            try:
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LlmUnavailable("Ответ без choices") from exc
            usage = data.get("usage") or {}
            return ChatResult(
                text=str(text),
                tokens_in=usage.get("prompt_tokens"),
                tokens_out=usage.get("completion_tokens"),
                model=str(data.get("model") or self.model),
            )
        raise LlmUnavailable("Токен отклонён")


def gigachat_from_settings(settings: Settings, redis: Redis) -> GigaChatClient | None:
    """None, если ключ или адреса не заданы, или OFFLINE_MODE — работают fallback-и."""
    if (
        settings.offline_mode
        or settings.gigachat_auth_key is None
        or not settings.gigachat_oauth_url
        or not settings.gigachat_api_url
    ):
        return None
    return GigaChatClient(
        auth_key=settings.gigachat_auth_key.get_secret_value(),
        scope=settings.gigachat_scope,
        oauth_url=settings.gigachat_oauth_url,
        api_url=settings.gigachat_api_url,
        model=settings.gigachat_model,
        redis=redis,
        ca_bundle=settings.gigachat_ca_bundle,
    )
