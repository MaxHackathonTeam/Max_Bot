"""Подписка бота на webhook (прод) и её снятие перед polling (локально), §9.2.

Сверено с github.com/max-messenger/api-schema: GET|POST|DELETE /subscriptions, секрет —
5–256 символов [A-Za-z0-9_-], приходит в заголовке X-Max-Bot-Api-Secret.
GET /subscriptions секрет не возвращает, а перезаписывает ли POST существующую подписку —
в схеме не сказано. Поэтому при старте API подписка пересоздаётся (DELETE + POST):
так в MAX всегда актуальный MAX_WEBHOOK_SECRET.
"""

import json
import re
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import structlog
from redis.asyncio import Redis

from app.core.config import Settings
from app.integrations.max import MaxClient
from app.integrations.max.client import UPDATE_TYPES

log = structlog.get_logger(__name__)

STATUS_KEY = "bot:webhook:status"
STATUS_TTL_S = 24 * 3600
SECRET_RE = re.compile(r"^[\w-]{5,256}$", re.ASCII)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}  # noqa: S104

Result = Literal["ok", "subscribed", "resubscribed"]


def config_problems(settings: Settings) -> list[str]:
    """Почему webhook не сможет работать. Пустой список — конфигурация в порядке."""
    problems: list[str] = []
    if settings.max_bot_token is None:
        problems.append("MAX_BOT_TOKEN не задан")
    secret = settings.max_webhook_secret
    if secret is None:
        problems.append("MAX_WEBHOOK_SECRET не задан")
    elif not SECRET_RE.match(secret.get_secret_value()):
        problems.append("MAX_WEBHOOK_SECRET: нужно 5–256 символов A-Z a-z 0-9 _ -")
    url = urlsplit(settings.public_base_url)
    if url.scheme != "https":
        problems.append("PUBLIC_BASE_URL должен начинаться с https://")
    if not url.hostname or url.hostname in _LOCAL_HOSTS or "." not in url.hostname:
        problems.append("PUBLIC_BASE_URL должен быть публичным доменом, не localhost")
    return problems


def _types_missing(sub: dict[str, Any]) -> bool:
    types = sub.get("update_types")
    # null в ответе — подписка на все типы (по схеме поле nullable).
    return types is not None and not set(UPDATE_TYPES) <= set(types)


async def ensure_webhook(client: MaxClient, url: str, secret: str, *, force: bool) -> Result:
    """Гарантирует подписку на url. force — пересоздать, даже если она есть (обновить секрет)."""
    subs = await client.list_subscriptions()
    mine = [s for s in subs if s.get("url") == url]
    foreign = [s for s in subs if s.get("url") != url]
    if foreign:
        # Чужие URL не снимаем автоматически: их видно в bot_doctor.
        log.warning("bot_webhook_foreign_subscriptions", count=len(foreign))
    if not mine:
        await client.subscribe(url, secret)
        log.info("bot_webhook_subscribed")
        return "subscribed"
    if force or any(_types_missing(s) for s in mine):
        await client.unsubscribe(url)
        await client.subscribe(url, secret)
        log.info("bot_webhook_resubscribed")
        return "resubscribed"
    return "ok"


async def save_status(redis: Redis, state: str, problems: list[str] | None = None) -> None:
    """Последний результат проверки подписки — для /ready и bot_doctor."""
    payload = {"state": state, "problems": problems or [], "checked_at": int(time.time())}
    try:
        await redis.set(STATUS_KEY, json.dumps(payload, ensure_ascii=False), ex=STATUS_TTL_S)
    except Exception as exc:  # статус справочный: его потеря не должна ронять проверку
        log.warning("bot_webhook_status_not_saved", error=type(exc).__name__)


async def load_status(redis: Redis) -> dict[str, Any] | None:
    raw = await redis.get(STATUS_KEY)
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


async def check_webhook(settings: Settings, redis: Redis, *, force: bool) -> str:
    """Проверка и восстановление подписки (старт API, cron воркера).

    Возвращает misconfigured | error | ok | restored.
    """
    problems = config_problems(settings)
    if problems:
        # Громко: без этого бот молча не получает обновлений.
        log.error("bot_webhook_not_configured", problems=problems)
        await save_status(redis, "misconfigured", problems)
        return "misconfigured"
    if settings.max_bot_token is None or settings.max_webhook_secret is None:  # проверено выше
        return "misconfigured"
    client = MaxClient(settings.max_bot_token.get_secret_value(), settings.max_api_base)
    try:
        result = await ensure_webhook(
            client,
            settings.webhook_url,
            settings.max_webhook_secret.get_secret_value(),
            force=force,
        )
    except Exception as exc:
        log.exception("bot_webhook_check_failed")
        await save_status(redis, "error", [f"MAX API: {type(exc).__name__}"])
        return "error"
    finally:
        await client.aclose()
    await save_status(redis, "ok")
    if result != "ok" and not force:
        # Подписка пропала или была неполной — восстановили.
        log.warning("bot_webhook_restored", result=result)
        return "restored"
    return "ok"


async def drop_webhooks(client: MaxClient) -> int:
    """При активном webhook long polling не работает — снимаем все подписки."""
    urls = [s["url"] for s in await client.list_subscriptions() if s.get("url")]
    for url in urls:
        await client.unsubscribe(url)
    if urls:
        log.warning("bot_webhooks_removed_for_polling", count=len(urls))
    return len(urls)
