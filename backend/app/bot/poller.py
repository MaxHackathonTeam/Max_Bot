"""Long polling бота для локального запуска (профиль compose `local`).

Заглушка этапа 0: реализация (GET /updates, снятие webhook) — на этапе 1.
"""

import asyncio

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging

log = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    log.warning("bot_poller_stub", message="Polling бота будет реализован на этапе 1")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
