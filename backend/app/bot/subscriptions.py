"""Подписка бота на webhook (прод) и её снятие перед polling (локально), §9.2."""

import structlog

from app.integrations.max import MaxClient

log = structlog.get_logger(__name__)


async def ensure_webhook(client: MaxClient, url: str, secret: str) -> bool:
    """Идемпотентно: подписываемся, только если подписки на url ещё нет. True — создана."""
    existing = {s.get("url") for s in await client.list_subscriptions()}
    if url in existing:
        log.info("bot_webhook_already_subscribed")
        return False
    await client.subscribe(url, secret)
    log.info("bot_webhook_subscribed")
    return True


async def drop_webhooks(client: MaxClient) -> int:
    """При активном webhook long polling не работает — снимаем все подписки."""
    urls = [s["url"] for s in await client.list_subscriptions() if s.get("url")]
    for url in urls:
        await client.unsubscribe(url)
    if urls:
        log.warning("bot_webhooks_removed_for_polling", count=len(urls))
    return len(urls)
