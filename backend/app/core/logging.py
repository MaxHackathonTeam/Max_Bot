"""structlog: JSON-логи с request_id из contextvars."""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    log_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
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
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "arq"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
