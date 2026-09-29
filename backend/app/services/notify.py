"""Сообщения пользователю в бот о результатах модерации и верификации.

Сервисы не знают, как доставляется сообщение: из API оно ставится в очередь,
из воркера и бота — отправляется сразу (app.bot.notify.BotNotifier).
Из очереди — с повторами (workers.settings.send_user_message) и дедупликацией по job_id.

Модераторам (ADMIN_MAX_USER_IDS) — всегда через очередь: alert_moderators и close_moderation.
kind: "e" — событие (id события), "v" — заявка организации на проверку (id заявки).
"""

import hashlib
from typing import Protocol

from app.core.jobs import ALERT_MODERATORS, CLOSE_MODERATION, SEND_USER_MESSAGE, JobQueue


class Notifier(Protocol):
    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        """user_id — внутренний id; deeplink — payload open_app (ev_<id>, org_<id>)."""
        ...

    async def alert_moderators(self, kind: str, entity_id: int) -> None:
        """Новая заявка ждёт решения: сообщение каждому модератору с кнопками."""
        ...

    async def moderation_closed(self, kind: str, entity_id: int) -> None:
        """Решение принято (в боте или на сайте): убрать кнопки у всех модераторов."""
        ...


class QueuedNotifier:
    def __init__(self, jobs: JobQueue) -> None:
        self._jobs = jobs

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        # Одинаковое сообщение тому же пользователю, пока задача жива, — одно (arq job_id).
        digest = hashlib.sha256(f"{user_id}\n{deeplink}\n{text}".encode()).hexdigest()[:24]
        await self._jobs.enqueue(SEND_USER_MESSAGE, user_id, text, deeplink, job_id=f"msg:{digest}")

    async def alert_moderators(self, kind: str, entity_id: int) -> None:
        await self._jobs.enqueue(
            ALERT_MODERATORS, kind, entity_id, job_id=f"mod:{kind}:{entity_id}"
        )

    async def moderation_closed(self, kind: str, entity_id: int) -> None:
        await self._jobs.enqueue(CLOSE_MODERATION, kind, entity_id)


class MemoryNotifier:
    """Для тестов."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []
        self.moderation: list[tuple[str, str, int]] = []

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        self.sent.append((user_id, text, deeplink))

    async def alert_moderators(self, kind: str, entity_id: int) -> None:
        self.moderation.append(("alert", kind, entity_id))

    async def moderation_closed(self, kind: str, entity_id: int) -> None:
        self.moderation.append(("closed", kind, entity_id))
