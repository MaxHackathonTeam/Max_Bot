"""Обработка обновлений бота (§12). Общая для webhook (через очередь) и polling."""

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import fsm, keyboards, render, texts
from app.bot.notify import BotNotifier
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import SessionMaker
from app.integrations.max import MaxClient
from app.models.enums import ConsentDoc
from app.models.users import User
from app.schemas.users import MeUpdate
from app.services import admin as admin_service
from app.services import drafts as drafts_service
from app.services import events as events_service
from app.services import localities as localities_service
from app.services import moderation as moderation_service
from app.services import orgs as orgs_service
from app.services import saved as saved_service
from app.services import search_parse, web_login
from app.services import users as users_service
from app.services import verification as verification_service
from app.services.categories import is_known
from app.services.notify import Notifier

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


FEED_PAGE = 5
SAVED_PAGE = 10
LOCALITY_OPTIONS = 5

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


def _message(text: str, keyboard: dict[str, Any] | None = None) -> dict[str, Any]:
    """Тело для замены сообщения через ответ на callback (CallbackAnswer.message)."""
    return {"text": text, "attachments": [keyboard] if keyboard else []}


async def _user(session: AsyncSession, target: _Target) -> User:
    return await users_service.upsert_from_max(
        session, target.max_user, dialog_chat_id=target.chat_id
    )


async def _send_consent(ctx: BotContext, target: _Target) -> None:
    consent_text = texts.CONSENT.format(
        terms_url=_legal_url(ctx, "terms"), privacy_url=_legal_url(ctx, "privacy")
    )
    await _send(ctx, target, consent_text, keyboards.consent())


# --- Онбординг: населённый пункт и интересы ------------------------------------------


async def _ask_locality(
    ctx: BotContext, target: _Target, state: str, lead: str | None = None
) -> None:
    await ctx.states.set(target.user_id, state)
    text = f"{lead}\n\n{texts.ASK_LOCALITY}" if lead else texts.ASK_LOCALITY
    await _send(ctx, target, text, keyboards.ask_locality())


async def _search_locality(ctx: BotContext, target: _Target, query: str) -> None:
    if len(query) < 2:
        await _send(ctx, target, texts.LOCALITY_TOO_SHORT, keyboards.ask_locality())
        return
    async with ctx.db() as session:
        found = await localities_service.search(session, query, LOCALITY_OPTIONS)
    if not found:
        text = texts.LOCALITY_NOT_FOUND.format(query=query[:64])
        await _send(ctx, target, text, keyboards.ask_locality())
        return
    options = [(loc.id, render.locality_label(loc)) for loc in found]
    await _send(ctx, target, texts.LOCALITY_CHOOSE, keyboards.localities(options))


async def _after_locality(ctx: BotContext, target: _Target, name: str) -> None:
    """Куда вести после выбора места: онбординг → интересы, настройки → настройки."""
    state = await ctx.states.get(target.user_id)
    saved = texts.LOCALITY_SAVED.format(name=name)
    if state == fsm.ONBOARDING_LOCALITY:
        await ctx.states.set(target.user_id, fsm.ONBOARDING_INTERESTS)
        await _send(ctx, target, saved)
        async with ctx.db() as session:
            user = await _user(session, target)
        await _send(ctx, target, texts.ASK_INTERESTS, keyboards.interests(user.interests or []))
        return
    await ctx.states.set(target.user_id, fsm.IDLE)
    if state == fsm.SETTINGS_LOCALITY:
        await _send(ctx, target, saved)
        await _send_settings(ctx, target)
    else:
        await _send_menu(ctx, target, saved)


async def _on_location(ctx: BotContext, target: _Target, lat: float, lon: float) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        found = await localities_service.nearest(session, lat, lon, limit=1)
        if found:
            await users_service.set_location(session, user, found[0].id, (lat, lon))
    if not found:
        await _send(ctx, target, texts.LOCALITY_GEO_NOT_FOUND, keyboards.ask_locality())
        return
    await _after_locality(ctx, target, found[0].name)


async def _choose_locality(
    ctx: BotContext, target: _Target, locality_id: int, answer: Answer
) -> None:
    async with ctx.db() as session:
        locality = await localities_service.get_out(session, locality_id)
        if locality is None:
            await answer(texts.FEED_EXPIRED_TOAST)
            return
        user = await _user(session, target)
        await users_service.set_location(session, user, locality.id)
    await answer(texts.LOCALITY_SAVED_TOAST.format(name=locality.name))
    await _after_locality(ctx, target, locality.name)


async def _toggle_interest(ctx: BotContext, target: _Target, slug: str, answer: Answer) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        current = list(user.interests or [])
        chosen = [s for s in current if s != slug] if slug in current else [*current, slug]
        patch = MeUpdate.model_validate({"interests": chosen})
        user = await users_service.update_profile(session, user, patch)
    await answer(message=_message(texts.ASK_INTERESTS, keyboards.interests(user.interests)))


async def _interests_done(ctx: BotContext, target: _Target) -> None:
    if await ctx.states.get(target.user_id) == fsm.ONBOARDING_INTERESTS:
        await ctx.states.set(target.user_id, fsm.IDLE)
        await _send_menu(ctx, target, texts.INTERESTS_SAVED)
    else:
        await _send_settings(ctx, target)


# --- Подборки ------------------------------------------------------------------------

_DATE_PRESETS: dict[str, events_service.DatePreset] = {"today": "today", "weekend": "weekend"}


async def _send_feed(
    ctx: BotContext,
    target: _Target,
    preset: str,
    radius: int | None = None,
    offset: int = 0,
    cursor: str | None = None,
) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        if user.locality_id is None:
            await _ask_locality(ctx, target, fsm.ONBOARDING_LOCALITY, texts.NEED_LOCALITY)
            return
        radius = radius or user.radius_km
        locality = await localities_service.get_out(session, user.locality_id)
        filters = events_service.EventFilters(
            locality_id=user.locality_id,
            radius_km=radius,
            date_preset=_DATE_PRESETS.get(preset),
            pushkin=preset == "pushkin",
            # Подборка бота — только «Официальные»: ленты доверия не смешиваются.
            tier="official",
            sort="date",
            cursor=cursor,
            limit=FEED_PAGE,
        )
        page = await events_service.search(session, filters)
    web_app = await ctx.web_app_name()
    title = texts.FEED_TITLES[preset]
    if not page.items:
        wider = next((r for r in events_service.RADIUS_CHOICES if r > radius), None)
        text = texts.FEED_EMPTY.format(title=title, radius=radius)
        await _send(ctx, target, text, keyboards.feed_empty(web_app, preset=preset, wider=wider))
        return
    place = locality.name if locality else "—"
    text = render.feed(title, place, radius, page.items, offset)
    items = [(c.id, c.next_session.id if c.next_session else None) for c in page.items]
    keyboard = keyboards.feed(
        web_app,
        items,
        preset=preset,
        radius=radius,
        next_cursor=page.next_cursor,
        offset=offset,
    )
    await _send(ctx, target, text, keyboard)


async def _on_phrase(ctx: BotContext, target: _Target, phrase: str) -> None:
    """FR-CAT-8: распознать фильтры, показать чипсы и применить FTS fallback."""
    async with ctx.db() as session:
        user = await _user(session, target)
        if user.locality_id is None:
            await _send(ctx, target, texts.UNKNOWN_TEXT, keyboards.menu_button())
            return
        parsed = await search_parse.parse(session, phrase)
        # Ни одного признака запроса — это не поиск, а просто сообщение.
        if parsed.fallback:
            await _send(ctx, target, texts.UNKNOWN_TEXT, keyboards.menu_button())
            return
        filters = events_service.EventFilters(
            locality_id=parsed.locality_id or user.locality_id,
            radius_km=user.radius_km,
            date_preset=cast(events_service.DatePreset | None, parsed.date),
            date_from=parsed.date_from,
            date_to=parsed.date_to,
            time_from=parsed.time_from,
            free=parsed.free,
            price_max=parsed.price_max,
            pushkin=parsed.pushkin,
            categories=list(parsed.categories),
            q=parsed.q,
            tier="official",
            limit=FEED_PAGE,
        )
        page = await events_service.search(session, filters)
        locality = await localities_service.get_out(
            session, filters.locality_id or user.locality_id
        )
    chips = " · ".join(parsed.chips) or "текстовый поиск"
    if not page.items:
        await _send(
            ctx,
            target,
            f"Понял так: {chips}\n\nНичего не нашёл — попробуй изменить запрос.",
            keyboards.menu_button(),
        )
        return
    await _send(
        ctx,
        target,
        render.feed(
            f"Понял так: {chips}", locality.name if locality else "—", user.radius_km, page.items
        ),
        keyboards.feed(
            await ctx.web_app_name(),
            [(c.id, c.next_session.id if c.next_session else None) for c in page.items],
            preset=parsed.date or "today",
            radius=user.radius_km,
            next_cursor=page.next_cursor,
        ),
    )


def _parse_feed(args: list[str]) -> tuple[str, int, int, str | None] | None:
    """feed:<preset>:<radius>:<offset>[:<cursor>] → аргументы; None, если payload битый."""
    if len(args) not in (3, 4) or args[0] not in texts.FEED_TITLES:
        return None
    if not (args[1].isdigit() and args[2].isdigit()):
        return None
    radius, offset = int(args[1]), int(args[2])
    if radius not in events_service.RADIUS_CHOICES or offset > 1000:
        return None
    return args[0], radius, offset, args[3] if len(args) == 4 else None


# --- «Пойду» -------------------------------------------------------------------------


async def _saved_view(ctx: BotContext, target: _Target) -> tuple[str, dict[str, Any]]:
    async with ctx.db() as session:
        user = await _user(session, target)
        items = (await saved_service.list_saved(session, user))[:SAVED_PAGE]
    if not items:
        return texts.SAVED_EMPTY, keyboards.menu_button()
    keyboard = keyboards.saved(
        await ctx.web_app_name(), [(i.event.id, i.session.id) for i in items]
    )
    return render.saved(items), keyboard


async def _save(
    ctx: BotContext, target: _Target, event_id: int, session_id: int, answer: Answer
) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        try:
            await saved_service.save(session, user, event_id, session_id)
        except AppError as exc:
            await answer(exc.message)
            if exc.code == "consent_required":
                await _send_consent(ctx, target)
            return
    await answer(texts.SAVED_TOAST)


async def _unsave(
    ctx: BotContext, target: _Target, event_id: int, session_id: int, answer: Answer
) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        await saved_service.unsave(session, user, event_id, session_id)
    text, keyboard = await _saved_view(ctx, target)
    await answer(texts.UNSAVED_TOAST, message=_message(text, keyboard))


# --- Настройки и удаление данных -----------------------------------------------------


async def _settings_view(ctx: BotContext, target: _Target) -> tuple[str, dict[str, Any]]:
    async with ctx.db() as session:
        user = await _user(session, target)
        locality = (
            await localities_service.get_out(session, user.locality_id)
            if user.locality_id is not None
            else None
        )
    text = render.settings(user, locality.name if locality else None)
    keyboard = keyboards.settings(
        user.radius_km, reminders=user.notify_reminders, digest=user.notify_digest
    )
    return text, keyboard


async def _send_settings(ctx: BotContext, target: _Target) -> None:
    await _send(ctx, target, *await _settings_view(ctx, target))


async def _update_settings(
    ctx: BotContext, target: _Target, patch: dict[str, Any], answer: Answer
) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        await users_service.update_profile(session, user, MeUpdate.model_validate(patch))
    text, keyboard = await _settings_view(ctx, target)
    await answer(texts.SETTINGS_SAVED_TOAST, message=_message(text, keyboard))


async def _toggle_setting(ctx: BotContext, target: _Target, name: str, answer: Answer) -> None:
    async with ctx.db() as session:
        current = bool(getattr(await _user(session, target), name))
    await _update_settings(ctx, target, {name: not current}, answer)


async def _delete_data(ctx: BotContext, target: _Target) -> None:
    async with ctx.db() as session:
        # Без upsert: после удаления max_user_id пуст, и upsert создал бы нового пользователя.
        user = await users_service.get_by_max_id(session, target.user_id)
        if user is not None:
            await users_service.delete_user_data(session, user)
    await ctx.states.set(target.user_id, fsm.IDLE)
    await _send(ctx, target, texts.DELETE_DONE)


# --- Организатор: меню и подтверждение телефона (§5.3 B.2) ----------------------------


async def _send_org_menu(ctx: BotContext, target: _Target) -> None:
    await _send(ctx, target, texts.ORG_MENU, keyboards.org_menu(await ctx.web_app_name()))


def _contact_of(body: dict[str, Any]) -> dict[str, Any] | None:
    """Вложение contact (schema.yaml: ContactAttachmentPayload: vcf_info, hash, max_info)."""
    for attachment in body.get("attachments") or []:
        if attachment.get("type") == "contact":
            payload = attachment.get("payload")
            return payload if isinstance(payload, dict) else {}
    return None


async def _on_contact(ctx: BotContext, target: _Target, payload: dict[str, Any]) -> None:
    max_info = payload.get("max_info") or {}
    contact = verification_service.ContactData(
        vcf_info=payload.get("vcf_info"),
        hash=payload.get("hash"),
        max_user_id=max_info.get("user_id") if isinstance(max_info, dict) else None,
    )
    token = ctx.settings.max_bot_token
    async with ctx.db() as session:
        user = await _user(session, target)
        result = await verification_service.confirm_phone(
            session,
            user,
            contact,
            token.get_secret_value() if token is not None else "",
            _notifier(ctx),
        )
    reply = {
        "ok": texts.PHONE_CONFIRMED,
        "no_request": texts.PHONE_NO_REQUEST,
        "bad_signature": texts.PHONE_BAD_SIGNATURE,
        "not_own": texts.PHONE_NOT_OWN,
    }[result]
    keyboard = keyboards.phone_request() if result in ("bad_signature", "not_own") else None
    await _send(ctx, target, reply, keyboard)


def _notifier(ctx: BotContext) -> Notifier:
    if ctx.notifier is not None:
        return ctx.notifier
    return BotNotifier(ctx.db, ctx.max, ctx.settings.max_bot_username)


# --- Очередь админа (§6 п. 5) ---------------------------------------------------------


def _is_admin(ctx: BotContext, target: _Target) -> bool:
    return target.user_id in ctx.settings.admin_max_user_ids


async def _send_queue(ctx: BotContext, target: _Target) -> None:
    if not _is_admin(ctx, target):
        await _send(ctx, target, texts.ADMIN_ONLY, keyboards.menu_button())
        return
    async with ctx.db() as session:
        data = await admin_service.queue(session, limit=10)
    if not data.events and not data.verifications:
        await _send(ctx, target, texts.QUEUE_EMPTY, keyboards.menu_button())
        return
    header = texts.QUEUE_HEADER.format(
        events=len(data.events), verifications=len(data.verifications)
    )
    await _send(ctx, target, header)
    web_app = await ctx.web_app_name()
    for item in data.events:
        when = (
            f" · {render.when(item.next_starts_at, localities_service.DEFAULT_TIMEZONE)}"
            if item.next_starts_at
            else ""
        )
        text = texts.QUEUE_EVENT.format(
            id=item.id,
            status=item.status,
            tier=item.trust_tier,
            title=item.title,
            org=item.org_name or "—",
            when=when,
            reason=item.moderation_reason or "",
        ).strip()
        await _send(
            ctx, target, text, keyboards.queue_event(web_app, item.id, item.organization_id)
        )
    for request in data.verifications:
        steps = "\n".join(
            f"{'✅' if s['status'] == 'ok' else '❌' if s['status'] == 'failed' else '⏳'} "
            f"{s['title']}" + (f": {s['message']}" if s.get("message") else "")
            for s in request.steps
        )
        text = texts.QUEUE_VERIFICATION.format(
            id=request.id,
            method=request.method,
            org=request.org_name,
            inn=request.inn or "—",
            steps=steps or texts.QUEUE_NO_STEPS,
        )
        await _send(ctx, target, text, keyboards.queue_verification(request.id))


async def _admin_user(ctx: BotContext, target: _Target) -> User:
    async with ctx.db() as session:
        return await _user(session, target)


async def _admin_apply(
    ctx: BotContext, target: _Target, kind: str, entity_id: int, action: str, reason: str | None
) -> str:
    """Применяет решение. Возвращает тост; AppError с кодом bad_transition → «уже решено»."""
    notifier = _notifier(ctx)
    async with ctx.db() as session:
        admin = await _user(session, target)
        try:
            if kind == "e":
                await moderation_service.admin_decide(
                    session, admin, entity_id, action, reason, notifier
                )
            elif kind == "v":
                await verification_service.decide(
                    session, admin, entity_id, action == "approve", reason, notifier
                )
            else:
                await orgs_service.revoke(session, admin, entity_id, reason)
        except AppError as exc:
            if exc.status_code == 409:
                return texts.QUEUE_ALREADY_TOAST
            return exc.message
    return texts.QUEUE_DONE_TOAST


async def _on_admin_callback(
    ctx: BotContext, target: _Target, args: list[str], answer: Answer
) -> None:
    if not _is_admin(ctx, target):
        await answer(texts.ADMIN_ONLY)
        return
    kind = args[0]
    entity_id = int(args[1])
    action = args[2] if len(args) == 3 else "revoke"
    if action == "reject":
        await answer()
        await ctx.states.set(target.user_id, f"{fsm.ADMIN_REASON}:{kind}:{entity_id}")
        await _send(ctx, target, texts.QUEUE_ASK_REASON)
        return
    reason = texts.QUEUE_REVOKE_REASON if kind == "r" else None
    toast = await _admin_apply(ctx, target, kind, entity_id, action, reason)
    await answer(toast)
    if toast == texts.QUEUE_DONE_TOAST:
        verdict = texts.QUEUE_VERDICTS[action]
        await _send(ctx, target, texts.QUEUE_DECIDED.format(id=entity_id, verdict=verdict))


def _parse_admin(args: list[str]) -> bool:
    if len(args) == 3 and args[0] == "e" and args[2] in ("approve", "reject", "hide"):
        return args[1].isdigit()
    if len(args) == 3 and args[0] == "v" and args[2] in ("approve", "reject"):
        return args[1].isdigit()
    return len(args) == 2 and args[0] == "r" and args[1].isdigit()


async def _on_admin_reason(ctx: BotContext, target: _Target, state: str, text: str) -> None:
    _, kind, raw_id = state.split(":")
    if len(text) < 5:
        await _send(ctx, target, texts.QUEUE_REASON_TOO_SHORT)
        return
    await ctx.states.set(target.user_id, fsm.IDLE)
    if not _is_admin(ctx, target):
        await _send(ctx, target, texts.ADMIN_ONLY)
        return
    toast = await _admin_apply(ctx, target, kind, int(raw_id), "reject", text[:500])
    if toast == texts.QUEUE_DONE_TOAST:
        toast = texts.QUEUE_DECIDED.format(id=raw_id, verdict=texts.QUEUE_VERDICTS["reject"])
    await _send(ctx, target, toast, keyboards.menu_button())


# --- Входящие ------------------------------------------------------------------------


async def _on_start(ctx: BotContext, target: _Target, payload: str | None) -> None:
    login_code = web_login.code_from_start(payload)
    if login_code is not None:
        await _ask_web_login(ctx, target, login_code)
        return
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
        if user.locality_id is None:
            await _ask_locality(ctx, target, fsm.ONBOARDING_LOCALITY)
        return
    await _send(ctx, target, greeting)
    await _send_consent(ctx, target)
    await _send_menu(ctx, target)


async def _ask_web_login(ctx: BotContext, target: _Target, code: str) -> None:
    async with ctx.db() as session:
        await users_service.upsert_from_max(
            session, target.max_user, dialog_chat_id=target.chat_id, bot_started=True
        )
    if ctx.redis is None:
        await _send(ctx, target, texts.WEB_LOGIN_UNAVAILABLE, keyboards.menu_button())
        return
    await _send(
        ctx, target, texts.WEB_LOGIN_CONFIRM.format(code=code), keyboards.web_login_confirm(code)
    )


async def _confirm_web_login(ctx: BotContext, target: _Target, code: str, answer: Answer) -> None:
    confirmed = False
    if ctx.redis is not None:
        async with ctx.db() as session:
            user = await _user(session, target)
            confirmed = await web_login.confirm(session, ctx.redis, code, user)
    if confirmed:
        await answer(texts.WEB_LOGIN_DONE_TOAST)
    else:
        await answer()
        await _send(ctx, target, texts.WEB_LOGIN_EXPIRED, keyboards.menu_button())


def _location_of(body: dict[str, Any]) -> tuple[float, float] | None:
    """Геопозиция из вложения location (schema.yaml: LocationAttachment)."""
    for attachment in body.get("attachments") or []:
        if attachment.get("type") != "location":
            continue
        try:
            lat, lon = float(attachment["latitude"]), float(attachment["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


_FEED_COMMANDS = {"/today": "today", "/weekend": "weekend", "/pushkin": "pushkin"}


async def _on_message(ctx: BotContext, target: _Target, update: dict[str, Any]) -> None:
    body = (update.get("message") or {}).get("body") or {}
    location = _location_of(body)
    if location is not None:
        await _on_location(ctx, target, *location)
        return
    contact = _contact_of(body)
    if contact is not None:
        await _on_contact(ctx, target, contact)
        return
    text = (body.get("text") or "").strip()
    forwarded = isinstance((update.get("message") or {}).get("link"), dict)
    # Пересланный пост может прийти без собственного текста: MAX кладёт его в link.body.
    if not text:
        linked = (update.get("message") or {}).get("link") or {}
        linked_body = linked.get("message", {}).get("body", {}) if isinstance(linked, dict) else {}
        text = str(linked_body.get("text") or "").strip()
    command, _, arg = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    if command == "/start":
        await _on_start(ctx, target, arg.strip() or None)
    elif command == "/menu":
        await ctx.states.set(target.user_id, fsm.IDLE)
        await _send_menu(ctx, target)
    elif command == "/help":
        await _send(ctx, target, texts.HELP, keyboards.menu_button())
    elif command in _FEED_COMMANDS:
        await _send_feed(ctx, target, _FEED_COMMANDS[command])
    elif command == "/saved":
        await _send(ctx, target, *await _saved_view(ctx, target))
    elif command == "/settings":
        await _send_settings(ctx, target)
    elif command == "/delete_me":
        await _send(ctx, target, texts.DELETE_CONFIRM, keyboards.delete_confirm())
    elif command == "/org":
        await _send_org_menu(ctx, target)
    elif command == "/queue":
        await _send_queue(ctx, target)
    elif text and (state := await ctx.states.get(target.user_id)).startswith(
        fsm.ADMIN_REASON + ":"
    ):
        await _on_admin_reason(ctx, target, state, text)
    elif text and await ctx.states.get(target.user_id) in (
        fsm.ONBOARDING_LOCALITY,
        fsm.SETTINGS_LOCALITY,
    ):
        await _search_locality(ctx, target, text)
    elif text and (
        forwarded
        or (len(text) >= 40 and re.search(r"\b\d{1,2}[./-]\d{1,2}\b|\b\d{1,2}:\d{2}\b", text))
    ):
        async with ctx.db() as session:
            user = await _user(session, target)
            event = await drafts_service.create_from_text(session, user, text, None)
        web_app = await ctx.web_app_name()
        await _send(
            ctx,
            target,
            "Сделал черновик из анонса. Проверь поля и дополни их в приложении.",
            keyboards.open_link(web_app, f"draft_{event.id}")
            if web_app
            else keyboards.menu_button(),
        )
    elif text:
        await _on_phrase(ctx, target, text)
    else:
        await _send_menu(ctx, target, texts.UNKNOWN_TEXT)


def _two_ints(args: list[str]) -> tuple[int, int] | None:
    if len(args) != 2 or not all(a.isdigit() for a in args):
        return None
    return int(args[0]), int(args[1])


async def _on_callback(
    ctx: BotContext, target: _Target, update: dict[str, Any], answered: list[bool]
) -> None:
    callback = update["callback"]
    payload = callback.get("payload") or ""

    async def answer(
        notification: str | None = None, *, message: dict[str, Any] | None = None
    ) -> None:
        # На каждый callback — ответ через POST /answers; повторное нажатие идемпотентно.
        await ctx.max.answer_callback(
            callback["callback_id"], notification=notification, message=message
        )
        answered[0] = True

    prefix, *args = payload.split(":")
    if payload == keyboards.CB_CONSENT_ACCEPT:
        async with ctx.db() as session:
            user = await _user(session, target)
            await users_service.accept_consents(
                session, user, [ConsentDoc.terms, ConsentDoc.privacy]
            )
        await answer(texts.CONSENT_ACCEPTED_TOAST)
        if user.locality_id is None:
            await _ask_locality(ctx, target, fsm.ONBOARDING_LOCALITY)
        else:
            await _send_menu(ctx, target)
    elif payload == keyboards.CB_MENU:
        await answer()
        await ctx.states.set(target.user_id, fsm.IDLE)
        await _send_menu(ctx, target)
    elif payload in keyboards.FEED_BY_MENU:
        await answer()
        await _send_feed(ctx, target, keyboards.FEED_BY_MENU[payload])
    elif payload == keyboards.CB_SAVED:
        await answer()
        await _send(ctx, target, *await _saved_view(ctx, target))
    elif payload == keyboards.CB_SETTINGS:
        await answer()
        await _send_settings(ctx, target)
    elif payload == keyboards.CB_ORG:
        await answer()
        await _send_org_menu(ctx, target)
    elif prefix == keyboards.P_ADMIN and _parse_admin(args):
        await _on_admin_callback(ctx, target, args, answer)
    elif payload in keyboards.SOON_CALLBACKS:
        await answer(texts.SOON_TOAST)
    elif payload == keyboards.CB_SET_LOCALITY:
        await answer()
        await _ask_locality(ctx, target, fsm.SETTINGS_LOCALITY)
    elif payload == keyboards.CB_SET_INTERESTS:
        await answer()
        async with ctx.db() as session:
            user = await _user(session, target)
        await _send(ctx, target, texts.ASK_INTERESTS, keyboards.interests(user.interests or []))
    elif payload == keyboards.CB_SET_REMINDERS:
        await _toggle_setting(ctx, target, "notify_reminders", answer)
    elif payload == keyboards.CB_SET_DIGEST:
        await _toggle_setting(ctx, target, "notify_digest", answer)
    elif payload == keyboards.CB_DELETE_ASK:
        await answer()
        await _send(ctx, target, texts.DELETE_CONFIRM, keyboards.delete_confirm())
    elif payload == keyboards.CB_DELETE_YES:
        await answer()
        await _delete_data(ctx, target)
    elif payload == keyboards.CB_DELETE_NO:
        await answer(texts.DELETE_CANCELLED_TOAST)
    elif prefix == keyboards.P_LOCALITY and len(args) == 1 and args[0].isdigit():
        await _choose_locality(ctx, target, int(args[0]), answer)
    elif prefix == keyboards.P_INTEREST and args == [keyboards.INTERESTS_DONE]:
        await answer()
        await _interests_done(ctx, target)
    elif prefix == keyboards.P_INTEREST and len(args) == 1 and is_known(args[0]):
        await _toggle_interest(ctx, target, args[0], answer)
    elif prefix == keyboards.P_RADIUS and args in (["5"], ["15"], ["30"], ["50"]):
        await _update_settings(ctx, target, {"radius_km": int(args[0])}, answer)
    elif prefix == keyboards.P_FEED and (parsed := _parse_feed(args)) is not None:
        await answer()
        preset, radius, offset, cursor = parsed
        try:
            await _send_feed(ctx, target, preset, radius, offset, cursor)
        except AppError as exc:
            if exc.code != "invalid_cursor":
                raise
            await _send(ctx, target, texts.FEED_EXPIRED_TOAST, keyboards.menu_button())
    elif (
        prefix == keyboards.P_WEB_LOGIN
        and len(args) == 1
        and (code := web_login.normalize(args[0])) is not None
    ):
        await _confirm_web_login(ctx, target, code, answer)
    elif prefix == keyboards.P_SAVE and (ids := _two_ints(args)) is not None:
        await _save(ctx, target, *ids, answer)
    elif prefix == keyboards.P_UNSAVE and (ids := _two_ints(args)) is not None:
        await _unsave(ctx, target, *ids, answer)
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
