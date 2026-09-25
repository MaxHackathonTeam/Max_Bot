"""Сообщения пользователю в бот о результатах модерации и верификации.

Сервисы не знают, как доставляется сообщение: из API оно ставится в очередь,
из воркера и бота — отправляется сразу (app.bot.notify.BotNotifier).
Полноценные уведомления с дедупликацией и тихими часами — этап 4.
"""

from typing import Protocol

from app.core.jobs import SEND_USER_MESSAGE, JobQueue


class Notifier(Protocol):
    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        """user_id — внутренний id; deeplink — payload open_app (ev_<id>, org_<id>)."""
        ...


class QueuedNotifier:
    def __init__(self, jobs: JobQueue) -> None:
        self._jobs = jobs

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        await self._jobs.enqueue(SEND_USER_MESSAGE, user_id, text, deeplink)


class MemoryNotifier:
    """Для тестов."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        self.sent.append((user_id, text, deeplink))
