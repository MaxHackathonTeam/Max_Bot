"""Обработка обновлений бота (§12). Общая для webhook (через очередь) и polling."""

import re
import uuid
from dataclasses import dataclass
from typing import Any

import structlog

from app.bot import keyboards, texts
from app.core.config import Settings
from app.db.session import SessionMaker
from app.integrations.max import MaxClient
from app.models.enums import ConsentDoc
from app.services import users as users_service

log = structlog.get_logger(__name__)

# Диплинки §3.1: ev_<id>, org_<id>, draft_<id>, inv_<token>, feed_<preset>.
_PAYLOAD_RE = re.compile(
    r"^(?:(?:ev|org|draft)_\d{1,18}|inv_[A-Za-z0-9_-]{8,128}|feed_(?:today|weekend|pushkin))$"
)
_DEEPLINK_TEXTS = {
    "ev": texts.DEEPLINK_EVENT,
    "org": texts.DEEPLINK_ORG,
    "draft": texts.DEEPLINK_DRAFT,
    "inv": texts.DEEPLINK_INVITE,
    "feed": texts.DEEPLINK_FEED,
}


def parse_start_payload(payload: str | None) -> str | None:
    """Возвращает payload диплинка, если он допустимый, иначе None."""
    if not payload:
        return None
    payload = payload.strip()
    return payload if _PAYLOAD_RE.match(payload) else None


@dataclass
class BotContext:
    settings: Settings
    db: SessionMaker
    max: MaxClient

    async def web_app_name(self) -> str | None:
        """Публичное имя бота для кнопки open_app: из env, иначе из GET /me."""
        if self.settings.max_bot_username:
            return self.settings.max_bot_username
        username = (await self.max.get_me()).get("username")
        return username if isinstance(username, str) and username else None


@dataclass(frozen=True)
class _Target:
    """Собеседник в личном диалоге с ботом."""

    max_user: dict[str, Any]
    chat_id: int | None

    @property
    def user_id(self) -> int:
        return int(self.max_user["user_id"])


def _target_of(update: dict[str, Any]) -> _Target | None:
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
    return _Target(max_user=user, chat_id=chat_id)


async def _send(
    ctx: BotContext, target: _Target, text: str, keyboard: dict[str, Any] | None = None
) -> None:
    attachments = [keyboard] if keyboard else None
    if target.chat_id is not None:
        await ctx.max.send_message(chat_id=target.chat_id, text=text, attachments=attachments)
    else:
        await ctx.max.send_message(user_id=target.user_id, text=text, attachments=attachments)


async def _send_menu(ctx: BotContext, target: _Target, text: str = texts.MENU) -> None:
    await _send(ctx, target, text, keyboards.main_menu(await ctx.web_app_name()))


def _legal_url(ctx: BotContext, doc: str) -> str:
    return f"{ctx.settings.public_base_url.rstrip('/')}/legal/{doc}"


async def _on_start(ctx: BotContext, target: _Target, payload: str | None) -> None:
    async with ctx.db() as session:
        user = await users_service.upsert_from_max(
            session, target.max_user, dialog_chat_id=target.chat_id, bot_started=True
        )
        consented = await users_service.has_required_consents(session, user)
    greeting = (
        texts.GREETING.format(name=user.first_name) if user.first_name else texts.GREETING_NO_NAME
    )

    deeplink = parse_start_payload(payload)
    web_app = await ctx.web_app_name()
    if deeplink and web_app:
        kind = deeplink.split("_", 1)[0]
        await _send(ctx, target, _DEEPLINK_TEXTS[kind], keyboards.open_app_with(web_app, deeplink))
    elif payload:
        log.info("bot_start_payload_ignored", payload_len=len(payload))

    if consented:
        await _send_menu(ctx, target, greeting)
        return
    await _send(ctx, target, greeting)
    consent_text = texts.CONSENT.format(
        terms_url=_legal_url(ctx, "terms"), privacy_url=_legal_url(ctx, "privacy")
    )
    await _send(ctx, target, consent_text, keyboards.consent())
    await _send_menu(ctx, target)


async def _on_message(ctx: BotContext, target: _Target, update: dict[str, Any]) -> None:
    body = (update.get("message") or {}).get("body") or {}
    text = (body.get("text") or "").strip()
    command, _, arg = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command == "/start":
        await _on_start(ctx, target, arg.strip() or None)
    elif command == "/menu":
        await _send_menu(ctx, target)
    elif command == "/help":
        await _send(ctx, target, texts.HELP, keyboards.menu_button())
    else:
        # Поиск фразой и черновики из текста — этапы 2 и 4.
        await _send_menu(ctx, target, texts.UNKNOWN_TEXT)


async def _on_callback(
    ctx: BotContext, target: _Target, update: dict[str, Any], answered: list[bool]
) -> None:
    callback = update["callback"]
    payload = callback.get("payload") or ""

    async def answer(notification: str | None = None) -> None:
        # На каждый callback — ответ через POST /answers; повторное нажатие идемпотентно.
        await ctx.max.answer_callback(callback["callback_id"], notification=notification)
        answered[0] = True

    if payload == keyboards.CB_CONSENT_ACCEPT:
        async with ctx.db() as session:
            user = await users_service.upsert_from_max(
                session, target.max_user, dialog_chat_id=target.chat_id
            )
            await users_service.accept_consents(
                session, user, [ConsentDoc.terms, ConsentDoc.privacy]
            )
        await answer(texts.CONSENT_ACCEPTED_TOAST)
        await _send_menu(ctx, target)
    elif payload == keyboards.CB_MENU:
        await answer()
        await _send_menu(ctx, target)
    elif payload in keyboards.SOON_CALLBACKS:
        await answer(texts.SOON_TOAST)
    else:
        log.info("bot_unknown_callback", payload_len=len(payload))
        await answer()


async def handle_update(ctx: BotContext, update: dict[str, Any]) -> None:
    """Глобальный обработчик: любое исключение → сообщение пользователю, бот не молчит."""
    kind = update.get("update_type")
    answered = [False]
    with structlog.contextvars.bound_contextvars(request_id=uuid.uuid4().hex, update_type=kind):
        try:
            target = _target_of(update)
            if target is None:
                log.debug("bot_update_skipped")
            elif kind == "bot_started":
                await _on_start(ctx, target, update.get("payload"))
            elif kind == "message_created":
                await _on_message(ctx, target, update)
            elif kind == "message_callback":
                await _on_callback(ctx, target, update, answered)
        except Exception:
            log.exception("bot_handler_failed")
            await _report_error(ctx, update, answered=answered[0])


async def _report_error(ctx: BotContext, update: dict[str, Any], *, answered: bool) -> None:
    try:
        callback_id = (update.get("callback") or {}).get("callback_id")
        if callback_id and not answered:
            await ctx.max.answer_callback(callback_id, notification=texts.ERROR)
        target = _target_of(update)
        if target is not None:
            await _send(ctx, target, texts.ERROR, keyboards.menu_button())
    except Exception:
        log.exception("bot_error_report_failed")
