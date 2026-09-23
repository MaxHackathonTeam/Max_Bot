"""Настройки arq-воркера. Задачи и cron появятся на следующих этапах."""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging

_settings = get_settings()
configure_logging(_settings.log_level)


# Для `arq --custom-log-dict`: не даём arq ставить свой текстовый handler, пишем через root (JSON).
ARQ_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {"arq": {"handlers": [], "propagate": True}},
}


async def ping(_ctx: dict[str, Any]) -> str:
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
    health_check_interval = 30
