"""Доставка сообщений пользователю в личный диалог с ботом (для воркера и бота)."""

from typing import Any

import structlog
from sqlalchemy import select

from app.bot import keyboards, render, texts
from app.core.config import Settings
from app.db.session import SessionMaker
from app.integrations.max import MaxClient
from app.models.events import Event, EventSession
from app.models.geo import Locality
from app.models.users import User
from app.services.localities import DEFAULT_TIMEZONE

log = structlog.get_logger(__name__)


class BotNotifier:
    def __init__(self, db: SessionMaker, client: MaxClient, web_app: str | None) -> None:
        self._db = db
        self._client = client
        self._web_app = web_app

    async def _recipient(self, user_id: int) -> tuple[int | None, int | None] | None:
        """(chat_id, max_user_id) — диалог, если известен, иначе пользователь MAX."""
        async with self._db() as session:
            user = await session.get(User, user_id)
        if user is None or user.deleted_at is not None:
            return None
        if user.max_user_id is None:
            # Гость сайта (/auth/guest): диалога с ботом у него нет — в бот не пишем.
            log.info("notify_guest_skipped", user_id=user_id)
            return None
        if user.dialog_chat_id is not None:
            return user.dialog_chat_id, None
        if user.max_user_id is not None:
            return None, user.max_user_id
        return None

    async def send_raw(
        self, user_id: int, text: str, keyboard: dict[str, Any] | None = None
    ) -> bool:
        recipient = await self._recipient(user_id)
        if recipient is None:
            log.info("notify_no_recipient", user_id=user_id)
            return False
        chat_id, max_user_id = recipient
        await self._client.send_message(
            chat_id=chat_id,
            user_id=max_user_id,
            text=text,
            attachments=[keyboard] if keyboard else None,
        )
        return True

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        keyboard = (
            keyboards.open_link(self._web_app, deeplink) if deeplink and self._web_app else None
        )
        await self.send_raw(user_id, text, keyboard)


async def notify_admins_new_event(
    db: SessionMaker, client: MaxClient, settings: Settings, event_id: int
) -> int:
    """Новая заявка на проверку → каждому из ADMIN_MAX_USER_IDS с кнопкой на /moderation/<id>.

    Возвращает число доставленных. Ошибка отправки одному модератору не мешает остальным.
    """
    admins = sorted(settings.admin_max_user_ids)
    if not admins:
        log.warning("admin_notify_no_admins", event_id=event_id)
        return 0
    async with db() as session:
        event = await session.get(Event, event_id)
        if event is None:
            return 0
        starts_at = await session.scalar(
            select(EventSession.starts_at)
            .where(EventSession.event_id == event_id)
            .order_by(EventSession.starts_at)
            .limit(1)
        )
        locality = await session.get(Locality, event.locality_id) if event.locality_id else None
        author = await session.get(User, event.author_user_id) if event.author_user_id else None
    tz = locality.timezone if locality and locality.timezone else DEFAULT_TIMEZONE
    author_name = " ".join(p for p in (author.first_name, author.last_name) if p) if author else ""
    text = texts.ADMIN_NEW_EVENT.format(
        id=event.id,
        title=event.title,
        when=render.when(starts_at, tz) if starts_at else "—",
        place=locality.name if locality else "—",
        author=author_name or "—",
        reason=(
            texts.ADMIN_NEW_EVENT_REASON.format(reason=event.moderation_reason)
            if event.moderation_reason
            else ""
        ),
    )
    base = settings.public_base_url.rstrip("/")
    url = f"{base}/moderation/{event.id}" if base.startswith("https://") else None
    keyboard = keyboards.admin_new_event(url, settings.max_bot_username or None, event.id)
    delivered = 0
    for max_user_id in admins:
        try:
            await client.send_message(
                user_id=max_user_id, text=text, attachments=[keyboard] if keyboard else None
            )
            delivered += 1
        except Exception as exc:
            log.warning("admin_notify_failed", event_id=event_id, error=type(exc).__name__)
    log.info("admin_notified", event_id=event_id, delivered=delivered, admins=len(admins))
    return delivered
