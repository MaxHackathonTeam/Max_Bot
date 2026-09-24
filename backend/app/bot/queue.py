"""Передача обновлений из webhook в очередь arq: webhook отвечает сразу, обработка в воркере."""

from typing import Any, Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

PROCESS_UPDATE_JOB = "process_bot_update"


class UpdateSink(Protocol):
    async def put(self, update: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


def update_job_id(update: dict[str, Any]) -> str:
    """Ключ дедупликации: MAX может повторить доставку того же обновления."""
    message = update.get("message") or {}
    ref = (
        (update.get("callback") or {}).get("callback_id")
        or (message.get("body") or {}).get("mid")
        or update.get("chat_id")
        or ""
    )
    return f"bot:{update.get('update_type')}:{update.get('timestamp')}:{ref}"


class ArqUpdateSink:
    def __init__(self, redis_url: str) -> None:
        self._settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def put(self, update: dict[str, Any]) -> None:
        if self._pool is None:
            self._pool = await create_pool(self._settings)
        await self._pool.enqueue_job(PROCESS_UPDATE_JOB, update, _job_id=update_job_id(update))

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
