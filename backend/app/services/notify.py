"""Сообщения пользователю в бот о результатах модерации и верификации.

Сервисы не знают, как доставляется сообщение: из API оно ставится в очередь,
из воркера и бота — отправляется сразу (app.bot.notify.BotNotifier).
Из очереди — с повторами (workers.settings.send_user_message) и дедупликацией по job_id.
"""

import hashlib
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
        # Одинаковое сообщение тому же пользователю, пока задача жива, — одно (arq job_id).
        digest = hashlib.sha256(f"{user_id}\n{deeplink}\n{text}".encode()).hexdigest()[:24]
        await self._jobs.enqueue(SEND_USER_MESSAGE, user_id, text, deeplink, job_id=f"msg:{digest}")


class MemoryNotifier:
    """Для тестов."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        self.sent.append((user_id, text, deeplink))
