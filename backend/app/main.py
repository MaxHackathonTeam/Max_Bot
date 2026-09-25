"""FastAPI app factory."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from app.api.bot_webhook import router as bot_webhook_router
from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.bot.queue import ArqUpdateSink
from app.bot.subscriptions import ensure_webhook
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.jobs import ArqJobQueue
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.db.session import make_engine, make_sessionmaker
from app.integrations.dadata.party import DadataPartyRegistry
from app.integrations.geo_factory import build_geo_provider
from app.integrations.gigachat.client import gigachat_from_settings
from app.integrations.max import client_from_settings
from app.llm.runner import LlmRunner

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
    jobs = ArqJobQueue(settings.redis_url)
    registry = (
        DadataPartyRegistry(settings.dadata_api_key.get_secret_value())
        if settings.dadata_api_key is not None and not settings.offline_mode
        else None
    )
    gigachat = gigachat_from_settings(settings, redis)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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
        await app.state.jobs.close()
        if registry is not None:
            await registry.aclose()
        if gigachat is not None:
            await gigachat.aclose()
        if app.state.max_client is not None:
            await app.state.max_client.aclose()
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
    app.state.jobs = jobs
    app.state.registry = registry
    app.state.max_client = client_from_settings(settings)
    app.state.llm = LlmRunner(gigachat, app.state.db, settings.llm_daily_token_budget)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    app.include_router(bot_webhook_router)
    # В проде /media/ раздаёт Caddy; здесь — для dev и тестов.
    app.mount("/media", StaticFiles(directory=settings.media_dir, check_dir=False), name="media")
    return app


app = create_app()
