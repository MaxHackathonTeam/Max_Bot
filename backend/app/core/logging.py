"""structlog: JSON-логи с request_id из contextvars."""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

_SENSITIVE = (
    "token",
    "secret",
    "password",
    "phone",
    "telephone",
    "auth",
    "authorization",
    "init_data",
)


def _mask(value: object, key: str = "") -> object:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if any(s in k.lower() for s in _SENSITIVE) else _mask(v, k))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask(item, key) for item in value]
    if isinstance(value, str) and any(s in key.lower() for s in _SENSITIVE):
        return "[REDACTED]"
    return value


def mask_pii(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    return {key: _mask(value, key) for key, value in event_dict.items()}


def configure_logging(level: str = "INFO") -> None:
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        mask_pii,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )
    # Сторонние библиотеки (uvicorn, arq) пишут через stdlib logging — тоже в JSON.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(ensure_ascii=False),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)
    for name in ("uvicorn", "uvicorn.error", "arq"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    # Запросы логирует RequestIdMiddleware, access-лог uvicorn дублировал бы их.
    logging.getLogger("uvicorn.access").disabled = True
