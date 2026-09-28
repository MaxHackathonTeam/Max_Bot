"""Обработка обновлений бота (§12). Общая для webhook (через очередь) и polling."""

import re
import uuid
from typing import Any, cast

import structlog

from app.bot import add_event, fsm, keyboards, render, texts
from app.bot.core import Answer, BotContext, event_path
from app.bot.core import Target as _Target
from app.bot.core import get_user as _user
from app.bot.core import message as _message
from app.bot.core import notifier_of as _notifier
from app.bot.core import send as _send
from app.bot.core import target_of as _target_of
from app.core.errors import AppError
from app.models.enums import ConsentDoc
from app.models.users import User
from app.schemas.events import EventCard, EventPage
from app.schemas.users import MeUpdate
from app.services import admin as admin_service
from app.services import event_editor, search_parse, web_login
from app.services import events as events_service
from app.services import localities as localities_service
from app.services import moderation as moderation_service
from app.services import orgs as orgs_service
from app.services import saved as saved_service
from app.services import users as users_service
from app.services import verification as verification_service
from app.services.categories import is_known

__all__ = ["BotContext", "handle_update", "parse_start_payload"]

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
MY_PAGE = 10
LOCALITY_OPTIONS = 5
# «Здесь пока нет событий»: ближайшие события ищем в этом радиусе.
NEAREST_PAGE = 3
TIERS = ("official", "community")
_TIER_CODE = {v: k for k, v in keyboards.TIER_CODES.items()}
# Похоже на анонс: дата «25.10» или время «18:00» в длинном тексте.
_ANNOUNCE_RE = re.compile(r"\b\d{1,2}[./-]\d{1,2}\b|\b\d{1,2}:\d{2}\b")
ANNOUNCE_MIN = 40


async def _place_name(ctx: BotContext, target: _Target) -> str | None:
    async with ctx.db() as session:
        user = await _user(session, target)
        if user.locality_id is None:
            return None
        locality = await localities_service.get_out(session, user.locality_id)
    return locality.name if locality else None


async def _send_menu(ctx: BotContext, target: _Target, text: str = texts.MENU) -> None:
    place = await _place_name(ctx, target)
    await _send(ctx, target, text, keyboards.main_menu(await ctx.web_app_name(), place))


async def _send_consent(ctx: BotContext, target: _Target) -> None:
    await _send(ctx, target, ctx.consent_text(), keyboards.consent())


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
    if state in (fsm.SETTINGS_LOCALITY, fsm.CITY_LOCALITY):
        await ctx.states.set(target.user_id, fsm.IDLE)
    if state == fsm.SETTINGS_LOCALITY:
        await _send(ctx, target, saved)
        await _send_settings(ctx, target)
    else:
        # Мастер «Добавить афишу» не сбрасываем: геопозиция могла прийти посреди него.
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

# Пресет подборки → фильтры ленты.
_PRESETS: dict[str, dict[str, Any]] = {
    "today": {"date_preset": "today"},
    "weekend": {"date_preset": "weekend"},
    "pushkin": {"pushkin": True},
    "kids": {"categories": ["kids"]},
    "free": {"free": True},
    "all": {},
}

FeedPage = tuple[str, EventPage]


def _feed_items(ctx: BotContext, cards: list[EventCard]) -> list[keyboards.FeedItem]:
    return [
        (c.id, c.next_session.id if c.next_session else None, ctx.site_url(f"/event/{c.id}"))
        for c in cards
    ]


async def _send_pages(
    ctx: BotContext,
    target: _Target,
    pages: list[FeedPage],
    *,
    title: str,
    place: str,
    radius: int,
    shown_radius: int | None,
    preset: str | None,
    offset: int = 0,
) -> None:
    """Каждая лента доверия — отдельным сообщением (§5.2): official и community не смешиваются."""
    web_app = await ctx.web_app_name()
    for tier, page in pages:
        text = render.feed(title, place, shown_radius, page.items, offset, tier=tier)
        keyboard = keyboards.feed(
            web_app,
            _feed_items(ctx, page.items),
            preset=preset,
            radius=radius,
            tier=_TIER_CODE[tier],
            next_cursor=page.next_cursor,
            offset=offset,
        )
        await _send(ctx, target, text, keyboard)


async def _search_tiers(ctx: BotContext, tiers: tuple[str, ...], **filters: Any) -> list[FeedPage]:
    pages: list[FeedPage] = []
    async with ctx.db() as session:
        for tier in tiers:
            page = await events_service.search(
                session,
                events_service.EventFilters(tier=cast(events_service.Tier, tier), **filters),
            )
            if page.items:
                pages.append((tier, page))
    return pages


async def _send_empty(
    ctx: BotContext,
    target: _Target,
    *,
    locality_id: int,
    place: str,
    preset: str | None,
    radius: int,
) -> None:
    """«Здесь пока нет событий» + ближайшие с расстоянием + «Добавь первое»."""
    nearest: list[FeedPage] = []
    async with ctx.db() as session:
        for tier in TIERS:
            page = await events_service.nearest(
                session,
                locality_id=locality_id,
                tier=cast(events_service.Tier, tier),
                limit=NEAREST_PAGE,
            )
            if page.items:
                nearest.append((tier, page))
    wider = next((r for r in events_service.RADIUS_CHOICES if r > radius), None)
    text = texts.EMPTY_HERE if nearest else f"{texts.EMPTY_HERE}\n\n{texts.EMPTY_NOWHERE}"
    await _send(ctx, target, text, keyboards.empty_here(preset=preset, wider=wider))
    await _send_pages(
        ctx,
        target,
        nearest,
        title=texts.EMPTY_NEAREST,
        place=place,
        radius=radius,
        shown_radius=None,
        preset=None,
    )


async def _send_feed(
    ctx: BotContext,
    target: _Target,
    preset: str,
    radius: int | None = None,
    offset: int = 0,
    cursor: str | None = None,
    tier: str | None = None,
) -> None:
    """Подборка по пресету. tier — только одна лента («Ещё» в ней); иначе обе по очереди."""
    async with ctx.db() as session:
        user = await _user(session, target)
        if user.locality_id is None:
            await _ask_locality(ctx, target, fsm.ONBOARDING_LOCALITY, texts.NEED_LOCALITY)
            return
        radius = radius or user.radius_km
        locality_id = user.locality_id
        locality = await localities_service.get_out(session, locality_id)
    place = locality.name if locality else "—"
    pages = await _search_tiers(
        ctx,
        (tier,) if tier else TIERS,
        locality_id=locality_id,
        radius_km=radius,
        sort="date",
        cursor=cursor,
        limit=FEED_PAGE,
        **_PRESETS[preset],
    )
    if not pages:
        if cursor:
            await _send(ctx, target, texts.FEED_NO_MORE, keyboards.find_menu())
            return
        await _send_empty(
            ctx, target, locality_id=locality_id, place=place, preset=preset, radius=radius
        )
        return
    await _send_pages(
        ctx,
        target,
        pages,
        title=texts.FEED_TITLES[preset],
        place=place,
        radius=radius,
        shown_radius=radius,
        preset=preset,
        offset=offset,
    )


async def _send_find(ctx: BotContext, target: _Target) -> None:
    await ctx.states.set(target.user_id, fsm.FIND_QUERY)
    await _send(ctx, target, texts.FIND_PROMPT, keyboards.find_menu())


async def _on_phrase(ctx: BotContext, target: _Target, phrase: str, *, explicit: bool) -> None:
    """FR-CAT-8: распознать фильтры, показать чипсы и применить FTS fallback.

    explicit — текст пришёл после /find: даже без признаков запроса это поиск по словам.
    """
    async with ctx.db() as session:
        user = await _user(session, target)
        parsed = await search_parse.parse(session, phrase)
        locality_id = parsed.locality_id or user.locality_id
        locality = await localities_service.get_out(session, locality_id) if locality_id else None
    # Ни одного признака запроса — это не поиск, а просто сообщение.
    if parsed.fallback and not explicit:
        await _send_menu(ctx, target, texts.UNKNOWN_TEXT)
        return
    if locality_id is None:
        await _ask_locality(ctx, target, fsm.ONBOARDING_LOCALITY, texts.NEED_LOCALITY)
        return
    pages = await _search_tiers(
        ctx,
        TIERS,
        locality_id=locality_id,
        radius_km=user.radius_km,
        date_preset=cast(events_service.DatePreset | None, parsed.date),
        date_from=parsed.date_from,
        date_to=parsed.date_to,
        time_from=parsed.time_from,
        free=parsed.free,
        price_max=parsed.price_max,
        pushkin=parsed.pushkin,
        categories=list(parsed.categories),
        q=parsed.q or (phrase if parsed.fallback else None),
        limit=FEED_PAGE,
    )
    chips = " · ".join(parsed.chips) or texts.FIND_TEXT_SEARCH
    if not pages:
        text = texts.FIND_NOTHING.format(chips=chips)
        await _send(ctx, target, text, keyboards.find_menu())
        return
    await _send_pages(
        ctx,
        target,
        pages,
        title=texts.FIND_UNDERSTOOD.format(chips=chips),
        place=locality.name if locality else "—",
        radius=user.radius_km,
        shown_radius=user.radius_km,
        preset=None,
    )


def _parse_feed(args: list[str]) -> tuple[str, int, str, int, str | None] | None:
    """feed:<preset>:<radius>:<o|c>:<offset>[:<cursor>] → аргументы; None, если payload битый.

    Старые кнопки без ленты (feed:<preset>:<radius>:<offset>[:<cursor>]) — это «Официальные».
    """
    if len(args) >= 3 and args[2] not in keyboards.TIER_CODES:
        args = [args[0], args[1], "o", *args[2:]]
    if len(args) not in (4, 5) or args[0] not in _PRESETS:
        return None
    if not (args[1].isdigit() and args[3].isdigit()):
        return None
    radius, offset = int(args[1]), int(args[3])
    if radius not in events_service.RADIUS_CHOICES or offset > 1000:
        return None
    tier = keyboards.TIER_CODES[args[2]]
    return args[0], radius, tier, offset, args[4] if len(args) == 5 else None


# --- Мои афиши -----------------------------------------------------------------------


async def _send_my(ctx: BotContext, target: _Target) -> None:
    async with ctx.db() as session:
        user = await _user(session, target)
        items = (await event_editor.my_events(session, user, None))[:MY_PAGE]
    if not items:
        await _send(ctx, target, texts.MY_EMPTY, keyboards.my_events(None, []))
        return
    links = [(i.id, ctx.site_url(event_path(i.id, i.status))) for i in items]
    await _send(
        ctx, target, render.my_events(items), keyboards.my_events(await ctx.web_app_name(), links)
    )


async def _send_myid(ctx: BotContext, target: _Target) -> None:
    role = texts.MYID_ADMIN if _is_admin(ctx, target) else texts.MYID_USER
    await _send(ctx, target, texts.MYID.format(user_id=target.user_id, role=role))


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

    # /start — всегда с чистого листа: брошенный мастер или поиск не мешают.
    await ctx.states.set(target.user_id, fsm.IDLE)
    await _send_menu(ctx, target, greeting)
    if user.locality_id is None:
        # Смотреть афишу можно без согласия (§4) — сразу предлагаем выбрать пункт.
        await _ask_locality(ctx, target, fsm.ONBOARDING_LOCALITY)
    elif not consented:
        await _send_consent(ctx, target)


async def _ask_web_login(ctx: BotContext, target: _Target, code: str) -> None:
    async with ctx.db() as session:
        user = await users_service.upsert_from_max(
            session, target.max_user, dialog_chat_id=target.chat_id, bot_started=True
        )
    if ctx.redis is None:
        await _send(ctx, target, texts.WEB_LOGIN_UNAVAILABLE, keyboards.menu_button())
        return
    name = " ".join(p for p in (user.first_name, user.last_name) if p) or texts.WEB_LOGIN_NO_NAME
    text = texts.WEB_LOGIN_CONFIRM.format(name=name, code=code)
    await _send(ctx, target, text, keyboards.web_login_confirm(code))


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
    command = command.split("@", 1)[0].lower() if command.startswith("/") else ""
    if command:
        await _on_command(ctx, target, command, arg.strip())
        return
    state = await ctx.states.get(target.user_id)
    if add_event.is_active(state):
        await add_event.on_message(ctx, target, state, text, add_event.image_url_of(body))
    elif not text:
        await _send_menu(ctx, target, texts.UNKNOWN_TEXT)
    elif state.startswith(fsm.ADMIN_REASON + ":"):
        await _on_admin_reason(ctx, target, state, text)
    elif state in (fsm.ONBOARDING_LOCALITY, fsm.SETTINGS_LOCALITY, fsm.CITY_LOCALITY):
        await _search_locality(ctx, target, text)
    elif forwarded or (len(text) >= ANNOUNCE_MIN and _ANNOUNCE_RE.search(text)):
        # Похоже на анонс — мастер разберёт его и покажет превью.
        await ctx.states.set(target.user_id, fsm.IDLE)
        await add_event.begin(ctx, target, text)
    else:
        explicit = state == fsm.FIND_QUERY
        if explicit:
            await ctx.states.set(target.user_id, fsm.IDLE)
        await _on_phrase(ctx, target, text, explicit=explicit)


async def _on_command(ctx: BotContext, target: _Target, command: str, arg: str) -> None:
    if command != "/start":
        # Команда прерывает незаконченный шаг (мастер, ввод пункта, поиск).
        await ctx.states.set(target.user_id, fsm.IDLE)
    if command == "/start":
        await _on_start(ctx, target, arg or None)
    elif command == "/menu":
        await _send_menu(ctx, target)
    elif command == "/help":
        await _send(ctx, target, texts.HELP, keyboards.menu_button())
    elif command == "/find":
        if arg:
            await _on_phrase(ctx, target, arg, explicit=True)
        else:
            await _send_find(ctx, target)
    elif command == "/add":
        await add_event.begin(ctx, target, arg or None)
    elif command == "/city":
        await _ask_locality(ctx, target, fsm.CITY_LOCALITY)
    elif command == "/my":
        await _send_my(ctx, target)
    elif command == "/myid":
        await _send_myid(ctx, target)
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
    else:
        await _send_menu(ctx, target, texts.UNKNOWN_COMMAND)


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
    elif payload == keyboards.CB_FIND:
        await answer()
        await _send_find(ctx, target)
    elif payload == keyboards.CB_ADD:
        await answer()
        await ctx.states.set(target.user_id, fsm.IDLE)
        await add_event.begin(ctx, target)
    elif payload == keyboards.CB_CITY:
        await answer()
        await _ask_locality(ctx, target, fsm.CITY_LOCALITY)
    elif payload == keyboards.CB_MY:
        await answer()
        await _send_my(ctx, target)
    elif prefix == keyboards.P_ADD:
        await add_event.on_callback(ctx, target, args, answer)
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
        preset, radius, tier, offset, cursor = parsed
        try:
            await _send_feed(ctx, target, preset, radius, offset, cursor, tier if cursor else None)
        except AppError as exc:
            if exc.code != "invalid_cursor":
                raise
            await _send(ctx, target, texts.FEED_EXPIRED_TOAST, keyboards.menu_button())
    elif prefix == keyboards.P_WEB_LOGIN and len(args) == 2 and args[0] == "no":
        await answer()
        await _send(ctx, target, texts.WEB_LOGIN_DENIED, keyboards.menu_button())
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
        # Кнопка из старого сообщения: отвечаем и показываем меню, а не молчим.
        log.info("bot_unknown_callback", payload_len=len(payload))
        await answer(texts.FEED_EXPIRED_TOAST)
        await _send_menu(ctx, target)


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
