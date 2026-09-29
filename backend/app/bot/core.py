"""Общее для обработчиков бота: контекст, собеседник, отправка сообщений.

Вынесено из dispatcher, чтобы мастер «Добавить афишу» (add_event) не зависел от него.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import fsm, texts
from app.bot.notify import BotNotifier
from app.core.config import Settings
from app.core.jobs import JobQueue, MemoryJobQueue
from app.db.session import SessionMaker
from app.integrations.max import MaxClient
from app.models.users import User
from app.services import users as users_service
from app.services.notify import Notifier

Answer = Callable[..., Awaitable[None]]


@dataclass
class BotContext:
    settings: Settings
    db: SessionMaker
    max: MaxClient
    states: fsm.StateStore = field(default_factory=fsm.MemoryStateStore)
    # Сообщения другим пользователям (автору события, владельцу организации).
    notifier: Notifier | None = None
    # Redis приложения: коды входа на сайте (services/web_login).
    redis: Any = None
    # Фоновые задачи (модерация события после отправки из мастера); в проде — arq.
    jobs: JobQueue = field(default_factory=MemoryJobQueue)

    async def web_app_name(self) -> str | None:
        """Публичное имя бота для кнопки open_app: из env, иначе из GET /me."""
        if self.settings.max_bot_username:
            return self.settings.max_bot_username
        username = (await self.max.get_me()).get("username")
        return username if isinstance(username, str) and username else None

    def site_url(self, path: str) -> str | None:
        """Ссылка на сайт для link-кнопки; None, если PUBLIC_BASE_URL не https (локально)."""
        base = self.settings.public_base_url.rstrip("/")
        return f"{base}{path}" if base.startswith("https://") else None

    def consent_text(self) -> str:
        base = self.settings.public_base_url.rstrip("/")
        return texts.CONSENT.format(
            terms_url=f"{base}/legal/terms", privacy_url=f"{base}/legal/privacy"
        )


def event_path(event_id: int, status: str) -> str:
    """Опубликованное — карточка на сайте, остальное автор видит в редакторе черновика."""
    return f"/event/{event_id}" if status == "published" else f"/draft/{event_id}"


@dataclass(frozen=True)
class Target:
    """Собеседник в личном диалоге с ботом."""

    max_user: dict[str, Any]
    chat_id: int | None

    @property
    def user_id(self) -> int:
        return int(self.max_user["user_id"])


def target_of(update: dict[str, Any]) -> Target | None:
    """Кому отвечать. None — не личный диалог (группы, каналы, другие боты)."""
    kind = update.get("update_type")
    if kind == "bot_started":
        user = update.get("user") or {}
        chat_id = update.get("chat_id")
    elif kind == "message_created":
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        user = message.get("sender") or {}
        if recipient.get("chat_type") != "dialog" or user.get("is_bot"):
            return None
        chat_id = recipient.get("chat_id")
    elif kind == "message_callback":
        user = (update.get("callback") or {}).get("user") or {}
        chat_id = ((update.get("message") or {}).get("recipient") or {}).get("chat_id")
    else:
        return None
    if "user_id" not in user:
        return None
    return Target(max_user=user, chat_id=chat_id)


async def send(
    ctx: BotContext, target: Target, text: str, keyboard: dict[str, Any] | None = None
) -> None:
    attachments = [keyboard] if keyboard else None
    if target.chat_id is not None:
        await ctx.max.send_message(chat_id=target.chat_id, text=text, attachments=attachments)
    else:
        await ctx.max.send_message(user_id=target.user_id, text=text, attachments=attachments)


def message(text: str, keyboard: dict[str, Any] | None = None) -> dict[str, Any]:
    """Тело для замены сообщения через ответ на callback (CallbackAnswer.message)."""
    return {"text": text, "attachments": [keyboard] if keyboard else []}


async def get_user(session: AsyncSession, target: Target) -> User:
    return await users_service.upsert_from_max(
        session, target.max_user, dialog_chat_id=target.chat_id
    )


def notifier_of(ctx: BotContext) -> Notifier:
    if ctx.notifier is not None:
        return ctx.notifier
    return BotNotifier(ctx.db, ctx.max, ctx.settings.max_bot_username, ctx.jobs)
