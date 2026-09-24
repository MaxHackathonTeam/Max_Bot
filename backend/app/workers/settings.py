"""Настройки arq-воркера. Задачи и cron появятся на следующих этапах."""

from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.bot.dispatcher import BotContext, handle_update
from app.bot.fsm import RedisStateStore
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import make_engine, make_sessionmaker
from app.integrations.geo_factory import build_geo_provider
from app.integrations.max import client_from_settings

_settings = get_settings()
configure_logging(_settings.log_level)
log = structlog.get_logger(__name__)


# Для `arq --custom-log-dict`: не даём arq ставить свой текстовый handler, пишем через root (JSON).
ARQ_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {"arq": {"handlers": [], "propagate": True}},
}


async def ping(_ctx: dict[str, Any]) -> str:
    return "pong"


async def process_bot_update(ctx: dict[str, Any], update: dict[str, Any]) -> None:
    """Имя задачи совпадает с app.bot.queue.PROCESS_UPDATE_JOB."""
    bot: BotContext | None = ctx.get("bot")
    if bot is None:
        log.warning("bot_update_dropped", reason="MAX_BOT_TOKEN не задан")
        return
    await handle_update(bot, update)


async def startup(ctx: dict[str, Any]) -> None:
    engine = make_engine(_settings.database_url)
    ctx["engine"] = engine
    redis = Redis.from_url(_settings.redis_url)
    ctx["app_redis"] = redis
    client = client_from_settings(_settings)
    if client is not None:
        ctx["bot"] = BotContext(
            settings=_settings,
            db=make_sessionmaker(engine),
            max=client,
            states=RedisStateStore(redis),
            geo=build_geo_provider(_settings, redis),
        )


async def shutdown(ctx: dict[str, Any]) -> None:
    bot: BotContext | None = ctx.get("bot")
    if bot is not None:
        await bot.max.aclose()
    await ctx["app_redis"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, process_bot_update]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    health_check_interval = 30
