"""Доставка сообщений пользователю в личный диалог с ботом (для воркера и бота)."""

from typing import Any

import structlog

from app.bot import keyboards
from app.db.session import SessionMaker
from app.integrations.max import MaxClient
from app.models.users import User

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
