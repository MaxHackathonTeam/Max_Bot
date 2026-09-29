"""Постановка фоновых задач в arq: модерация, проверки верификации, сообщения в бот.

Имена задач совпадают с функциями в app.workers.settings.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

MODERATE_EVENT = "moderate_event"
CHECK_VERIFICATION = "check_verification"
SEND_USER_MESSAGE = "send_user_message"
# Кнопка «Поделиться контактом» в боте после заявки на проверку способом Б.
REQUEST_PHONE = "request_phone"
# Заявка на модерацию → сообщения модераторам; решение принято → правка их сообщений.
ALERT_MODERATORS = "alert_moderators"
CLOSE_MODERATION = "close_moderation"


class JobQueue(Protocol):
    async def enqueue(
        self,
        name: str,
        *args: Any,
        defer_s: float | None = None,
        job_id: str | None = None,
    ) -> None: ...

    async def close(self) -> None: ...


class ArqJobQueue:
    def __init__(self, redis_url: str) -> None:
        self._settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def enqueue(
        self,
        name: str,
        *args: Any,
        defer_s: float | None = None,
        job_id: str | None = None,
    ) -> None:
        if self._pool is None:
            self._pool = await create_pool(self._settings)
        await self._pool.enqueue_job(name, *args, _defer_by=defer_s, _job_id=job_id)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


@dataclass
class QueuedJob:
    name: str
    args: tuple[Any, ...]
    defer_s: float | None
    job_id: str | None


@dataclass
class MemoryJobQueue:
    """Для тестов: задачи копятся в списке, тест выполняет их сам."""

    jobs: list[QueuedJob] = field(default_factory=list)

    async def enqueue(
        self,
        name: str,
        *args: Any,
        defer_s: float | None = None,
        job_id: str | None = None,
    ) -> None:
        self.jobs.append(QueuedJob(name, args, defer_s, job_id))

    async def close(self) -> None:
        return None

    def named(self, name: str) -> list[QueuedJob]:
        return [j for j in self.jobs if j.name == name]
