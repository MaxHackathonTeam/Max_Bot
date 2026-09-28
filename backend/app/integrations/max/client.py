"""Тонкий httpx-клиент MAX Bot API.

Сверено с официальной OpenAPI-схемой github.com/max-messenger/api-schema (schema.yaml):
POST /messages?user_id|chat_id, POST /answers?callback_id, GET /updates,
GET|POST|DELETE /subscriptions, GET /me, PATCH /me/commands.
Авторизация — заголовок `Authorization: <token>`.
"""

import asyncio
import time
from typing import Any

import httpx
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_TIMEOUT_S = 10.0
# Типы обновлений, которые обрабатывает бот (§12).
UPDATE_TYPES = ("bot_started", "message_created", "message_callback")


class MaxApiError(Exception):
    def __init__(self, status_code: int, code: str | None, message: str) -> None:
        super().__init__(f"MAX API {status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code


class MaxClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://platform-api2.max.ru",
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        retries: int = 3,
        backoff_s: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": token},
            timeout=timeout_s,
            transport=transport,
        )
        self._retries = retries
        self._backoff_s = backoff_s
        self._me: dict[str, Any] | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout_s: float | None = None,
    ) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        timeout: Any = httpx.USE_CLIENT_DEFAULT if timeout_s is None else timeout_s
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                response = await self._http.request(
                    method, path, params=params, json=json, timeout=timeout
                )
            except httpx.TransportError as exc:
                if attempt >= self._retries:
                    log.warning(
                        "max_api_transport_error",
                        method=method,
                        path=path,
                        error=type(exc).__name__,
                    )
                    raise
                await self._sleep(attempt, None)
                attempt += 1
                continue
            # В логах только метод, путь и статус — без параметров и тел (там ПДн).
            log.info(
                "max_api_call",
                method=method,
                path=path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                attempt=attempt,
            )
            if response.status_code in RETRY_STATUSES and attempt < self._retries:
                await self._sleep(attempt, response.headers.get("Retry-After"))
                attempt += 1
                continue
            if response.is_error:
                raise _error_from(response)
            return response.json() if response.content else None

    async def _sleep(self, attempt: int, retry_after: str | None) -> None:
        delay = self._backoff_s * 2**attempt
        if retry_after and retry_after.isdigit():
            delay = max(delay, min(float(retry_after), 30.0))
        await asyncio.sleep(delay)

    # --- методы API ---

    async def get_me(self) -> dict[str, Any]:
        """Информация о боте (кэшируется: нужна для кнопки open_app)."""
        if self._me is None:
            self._me = await self.request("GET", "/me")
        return self._me

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        notify: bool = True,
    ) -> dict[str, Any]:
        if (user_id is None) == (chat_id is None):
            raise ValueError("Нужен ровно один получатель: user_id или chat_id")
        body: dict[str, Any] = {"text": text, "notify": notify}
        if attachments:
            body["attachments"] = attachments
        result: dict[str, Any] = await self.request(
            "POST", "/messages", params={"user_id": user_id, "chat_id": chat_id}, json=body
        )
        return result

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
        message: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if notification is not None:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        await self.request("POST", "/answers", params={"callback_id": callback_id}, json=body)

    async def get_updates(
        self,
        marker: int | None = None,
        *,
        timeout_s: int = 30,
        limit: int = 100,
        types: tuple[str, ...] = UPDATE_TYPES,
    ) -> tuple[list[dict[str, Any]], int | None]:
        data = await self.request(
            "GET",
            "/updates",
            params={
                "marker": marker,
                "timeout": timeout_s,
                "limit": limit,
                "types": ",".join(types),
            },
            # HTTP-таймаут длиннее long polling.
            timeout_s=timeout_s + 15,
        )
        return list(data.get("updates") or []), data.get("marker")

    async def list_subscriptions(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/subscriptions")
        return list(data.get("subscriptions") or [])

    async def subscribe(
        self, url: str, secret: str, update_types: tuple[str, ...] = UPDATE_TYPES
    ) -> None:
        await self.request(
            "POST",
            "/subscriptions",
            json={"url": url, "secret": secret, "update_types": list(update_types)},
        )

    async def unsubscribe(self, url: str) -> None:
        await self.request("DELETE", "/subscriptions", params={"url": url})

    async def set_commands(self, commands: list[tuple[str, str]]) -> None:
        """Меню команд бота: PATCH /me/commands (BotCommandsPatch, не больше 32 команд)."""
        body = {"commands": [{"name": n, "description": d} for n, d in commands[:32]]}
        await self.request("PATCH", "/me/commands", json=body)

    async def download(self, url: str, max_bytes: int) -> bytes:
        """Файл вложения (PhotoAttachmentPayload.url). Только https, без редиректов, с лимитом."""
        if not url.startswith("https://"):
            raise ValueError("Ожидается https-ссылка на вложение")
        # Отдельный клиент: ссылка ведёт на CDN, токен бота туда не отправляем.
        async with (
            httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S, follow_redirects=False) as http,
            http.stream("GET", url) as response,
        ):
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data += chunk
                if len(data) > max_bytes:
                    raise ValueError("Вложение больше допустимого размера")
            return bytes(data)


def client_from_settings(settings: Settings) -> MaxClient | None:
    """None, если токен бота не задан (локальный запуск без бота)."""
    if settings.max_bot_token is None:
        return None
    return MaxClient(settings.max_bot_token.get_secret_value(), settings.max_api_base)


def _error_from(response: httpx.Response) -> MaxApiError:
    code: str | None = None
    message = response.reason_phrase
    try:
        data = response.json()
        code = data.get("code")
        message = data.get("message") or message
    except ValueError:
        pass
    return MaxApiError(response.status_code, code, message)
