"""FastAPI app factory."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.bot_webhook import router as bot_webhook_router
from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.bot.queue import ArqUpdateSink
from app.bot.subscriptions import ensure_webhook
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.db.session import make_engine, make_sessionmaker
from app.integrations.geo_factory import build_geo_provider
from app.integrations.max import client_from_settings

log = structlog.get_logger(__name__)


async def _subscribe_webhook(settings: Settings) -> None:
    client = client_from_settings(settings)
    if client is None or settings.max_webhook_secret is None:
        log.warning("bot_webhook_not_configured")
        return
    try:
        await ensure_webhook(
            client, settings.webhook_url, settings.max_webhook_secret.get_secret_value()
        )
    except Exception:
        # API продолжает работать; подписку можно повторить перезапуском.
        log.exception("bot_webhook_subscribe_failed")
    finally:
        await client.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    update_sink = ArqUpdateSink(settings.redis_url)
    redis = Redis.from_url(settings.redis_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log.info(
            "startup", env=settings.env, dev_auth=settings.dev_auth, bot_mode=settings.bot_mode
        )
        subscribe_task = None
        if settings.bot_mode == "webhook":
            subscribe_task = asyncio.create_task(_subscribe_webhook(settings))
        yield
        if subscribe_task is not None:
            subscribe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await subscribe_task
        await update_sink.close()
        await redis.aclose()
        await engine.dispose()
        log.info("shutdown")

    app = FastAPI(
        title="Афиша рядом API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.db = make_sessionmaker(engine)
    app.state.update_sink = update_sink
    app.state.redis = redis
    app.state.geo = build_geo_provider(settings, redis)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    app.include_router(bot_webhook_router)
    return app


app = create_app()
