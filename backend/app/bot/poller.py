"""Long polling бота для локального запуска (профиль compose `local`, BOT_MODE=polling).

При активном webhook GET /updates не работает. Снимать подписки poller будет только с
BOT_POLLER_TAKEOVER=1 — иначе локальный запуск с боевым токеном отключил бы прод-бота.
"""

import asyncio

import structlog
from redis.asyncio import Redis

from app.bot.dispatcher import BotContext, handle_update
from app.bot.fsm import RedisStateStore
from app.bot.subscriptions import drop_webhooks
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import make_engine, make_sessionmaker
from app.integrations.max import client_from_settings

log = structlog.get_logger(__name__)

MAX_BACKOFF_S = 30.0


async def poll(ctx: BotContext, stop: asyncio.Event) -> None:
    marker: int | None = None
    backoff = 1.0
    while not stop.is_set():
        try:
            updates, next_marker = await ctx.max.get_updates(marker)
        except Exception:
            log.exception("bot_poll_failed", retry_in_s=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            continue
        backoff = 1.0
        if next_marker is not None:
            marker = next_marker
        for update in updates:
            await handle_update(ctx, update)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    client = client_from_settings(settings)
    if client is None:
        log.warning("bot_poller_idle", message="MAX_BOT_TOKEN не задан — бот не запущен")
        await asyncio.Event().wait()
        return
    engine = make_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    ctx = BotContext(
        settings=settings,
        db=make_sessionmaker(engine),
        max=client,
        states=RedisStateStore(redis),
        redis=redis,
    )
    try:
        subs = await client.list_subscriptions()
        if subs and not settings.bot_poller_takeover:
            log.error(
                "bot_poller_refused",
                message="У бота есть webhook-подписка (прод?). Polling её снимет и прод-бот "
                "замолчит. Если это действительно нужно — BOT_POLLER_TAKEOVER=1.",
                subscriptions=len(subs),
            )
            await asyncio.Event().wait()
            return
        await drop_webhooks(client)
        log.info("bot_poller_started")
        await poll(ctx, asyncio.Event())
    finally:
        await client.aclose()
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
