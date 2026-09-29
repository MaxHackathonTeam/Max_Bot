"""Мастер «Добавить афишу» (§12): только по шагам.

Шаги: title → when → place → venue → category → price → description → cover → preview.
Состояние — add.<шаг> (fsm.ADD_PREFIX), поля черновика — в данных FSM (Redis, TTL 24 ч).
Ответы на шаги (дата, цена) разбирают детерминированные правила (app.parsing.extract).
В БД событие появляется только по «Отправить на проверку»: те же event_editor.create/patch
и submit, что у формы на сайте, — с правилами §6, лимитами, аудитом и уровнем доверия
(community по умолчанию, official — от проверенной организации, где состоит автор).
Опубликовать может только модератор.
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog

from app.bot import fsm, keyboards, render, texts
from app.bot.core import (
    Answer,
    BotContext,
    Target,
    event_deeplink,
    get_user,
    notifier_of,
    send,
)
from app.core.errors import AppError
from app.models.enums import EventStatus
from app.moderation import rules
from app.parsing import extract
from app.schemas.manage import EventCreate, EventPatch
from app.schemas.venues import VenueIn
from app.services import event_editor
from app.services import localities as localities_service
from app.services import media as media_service
from app.services import orgs as orgs_service
from app.services import users as users_service
from app.services import venues as venues_service
from app.services.categories import BY_SLUG, is_known
from app.services.notify import Notifier

log = structlog.get_logger(__name__)

STEPS = ("title", "when", "place", "venue", "category", "price", "description", "cover", "preview")
EDITABLE = STEPS[:-1]
OPTIONAL = frozenset({"venue", "description", "cover"})
REQUIRED = ("title", "when", "place", "category", "price")
ORG = "org"  # от проверенной организации или от себя
OPTIONS = 5
TITLE_MIN = 3
PREVIEW_DESCRIPTION = 1500

# Поле из ошибки сервиса (details.fields[].field) → шаг мастера.
_FIELD_STEPS = {
    "title": "title",
    "sessions": "when",
    "starts_at": "when",
    "locality_id": "place",
    "venue_id": "place",
    "category": "category",
    "price_type": "price",
    "price_min": "price",
    "price_max": "price",
    "description": "description",
    "short_description": "description",
    "cover_media_id": "cover",
}
_SKIP_KEYS = {
    "venue": ("venue_id", "venue_name", "venue_new_name"),
    "description": ("description",),
    "cover": ("cover_media_id",),
}
_DIGITS = re.compile(r"^\s*(\d{1,7})\s*(?:₽|руб\w*\.?|р\.?)?\s*$", re.I)


def state_of(step: str) -> str:
    return fsm.ADD_PREFIX + step


def is_active(state: str) -> bool:
    return state.startswith(fsm.ADD_PREFIX)


def image_url_of(body: dict[str, Any]) -> str | None:
    """Ссылка на картинку из вложения image (api-schema: PhotoAttachmentPayload.url)."""
    for attachment in body.get("attachments") or []:
        if attachment.get("type") == "image":
            url = (attachment.get("payload") or {}).get("url")
            return url if isinstance(url, str) else None
    return None


def parse_when(text: str, now: datetime) -> datetime | None:
    """«25.10 18:00», «завтра в 19:00», «в субботу 12:00» → начало; только будущее."""
    today = now.date()
    hit = extract.find_date(text, today)
    if hit is None:
        return None
    if hit.preset == "today":
        day = today
    elif hit.preset == "tomorrow":
        day = today + timedelta(days=1)
    elif hit.preset == "weekend":
        day = today + timedelta(days=(5 - today.weekday()) % 7)
    elif hit.date_from is not None:
        day = hit.date_from
    else:
        return None
    date_end = max((end for _, end in hit.spans), default=0)
    times = extract.find_times(text)
    # «12.10 18:00»: «12.10» похоже на время — берём время после даты.
    after = [t for t, (start, _) in times if start >= date_end] or [t for t, _ in times]
    if not after:
        return None
    start = datetime.combine(day, after[0], tzinfo=now.tzinfo)
    return start if start > now else None


def _tz(data: dict[str, Any]) -> ZoneInfo:
    mine = data.get("user_locality") or [None, None, None]
    return ZoneInfo(data.get("tz") or mine[2] or localities_service.DEFAULT_TIMEZONE)


def _start(data: dict[str, Any]) -> datetime | None:
    raw = data.get("start_local")
    return datetime.fromisoformat(raw).replace(tzinfo=_tz(data)) if raw else None


def _mark(data: dict[str, Any], step: str) -> None:
    if step not in data["filled"]:
        data["filled"].append(step)


def _set_price(
    data: dict[str, Any], kind: str, low: Decimal | None = None, high: Decimal | None = None
) -> None:
    data["price_type"] = kind
    data["price_min"] = str(low) if low is not None else None
    data["price_max"] = str(high) if high is not None else None


def _price_label(data: dict[str, Any]) -> str:
    kind = data.get("price_type")
    if kind == "free":
        return texts.PRICE_FREE
    if kind == "donation":
        return texts.PRICE_DONATION
    if kind != "paid" or not data.get("price_min"):
        return texts.ADD_PREVIEW_NONE
    low = f"{Decimal(data['price_min']):,.0f}".replace(",", " ")
    if data.get("price_max") and data["price_max"] != data["price_min"]:
        return texts.PRICE_FROM.format(price=low)
    return texts.PRICE_EXACT.format(price=low)


class _ExceptAuthor:
    """Автору мастер отвечает сам — уведомление ему не дублируем, остальным — как обычно."""

    def __init__(self, inner: Notifier, author_id: int) -> None:
        self._inner = inner
        self._author_id = author_id

    async def send(self, user_id: int, text: str, deeplink: str | None = None) -> None:
        if user_id != self._author_id:
            await self._inner.send(user_id, text, deeplink)

    async def alert_moderators(self, kind: str, entity_id: int) -> None:
        await self._inner.alert_moderators(kind, entity_id)

    async def moderation_closed(self, kind: str, entity_id: int) -> None:
        await self._inner.moderation_closed(kind, entity_id)


# --- Вход в мастер -----------------------------------------------------------------------


async def _save(ctx: BotContext, target: Target, step: str, data: dict[str, Any]) -> None:
    await ctx.states.set(target.user_id, state_of(step))
    await ctx.states.set_data(target.user_id, data)


async def begin(ctx: BotContext, target: Target) -> None:
    """/add и «➕ Добавить афишу»."""
    async with ctx.db() as session:
        user = await get_user(session, target)
        consented = await users_service.has_required_consents(session, user)
        orgs = (
            {
                str(org.id): org.name
                for org, _ in await orgs_service.list_mine(session, user)
                if orgs_service.is_verified(org)
            }
            if consented
            else {}
        )
        locality = (
            await localities_service.get_out(session, user.locality_id)
            if user.locality_id is not None
            else None
        )
    if not consented:
        # Публиковать может только пользователь, принявший условия (§4).
        prompt = f"{texts.ADD_NEED_CONSENT}\n\n{texts.CONSENT}"
        await send(ctx, target, prompt, keyboards.consent(await ctx.web_app_name()))
        return
    data: dict[str, Any] = {"filled": [], "org_id": None, "org_name": None}
    if locality is not None:
        data["user_locality"] = [locality.id, locality.name, locality.timezone]
    if orgs:
        data["orgs"] = orgs
        await _save(ctx, target, ORG, data)
        await _ask_org(ctx, target, data)
        return
    await _ask(ctx, target, "title", data, lead=texts.ADD_START)


async def _ask_org(ctx: BotContext, target: Target, data: dict[str, Any]) -> None:
    options = [(int(k), v) for k, v in data.get("orgs", {}).items()]
    await send(ctx, target, texts.ADD_CHOOSE_ORG, keyboards.add_orgs(options))


# --- Шаги --------------------------------------------------------------------------------


async def _next(ctx: BotContext, target: Target, data: dict[str, Any], after: str | None) -> None:
    """Следующий незаполненный шаг; после правки из превью — сразу к превью."""
    if data.pop("editing", False):
        await _ask(ctx, target, "preview", data)
        return
    first = STEPS.index(after) + 1 if after else 0
    step = next(s for s in STEPS[first:] if s == "preview" or s not in data["filled"])
    await _ask(ctx, target, step, data)


async def _ask(
    ctx: BotContext, target: Target, step: str, data: dict[str, Any], lead: str | None = None
) -> None:
    await _save(ctx, target, step, data)
    keyboard: dict[str, Any]
    if step == "preview":
        text, keyboard = _preview(data)
    else:
        text = texts.ADD_ASK[step]
        if step == "place":
            mine = data.get("user_locality")
            options = [(mine[0], texts.ADD_PLACE_MINE.format(name=mine[1]))] if mine else []
            keyboard = keyboards.add_places(options)
        elif step == "venue":
            keyboard = keyboards.add_step(skip=True)
        elif step == "category":
            keyboard = keyboards.add_categories()
        elif step == "price":
            keyboard = keyboards.add_price()
        else:
            keyboard = keyboards.add_step(skip=step in OPTIONAL)
    await send(ctx, target, f"{lead}\n\n{text}" if lead else text, keyboard)


def _preview(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    start = _start(data)
    has_cover = bool(data.get("cover_media_id"))
    place = ", ".join(p for p in (data.get("venue_name"), data.get("locality_name")) if p)
    category = BY_SLUG.get(data.get("category") or "")
    tier = (
        texts.ADD_TIER_OFFICIAL.format(org=data["org_name"])
        if data.get("org_id")
        else texts.ADD_TIER_COMMUNITY
    )
    description = data.get("description") or texts.ADD_PREVIEW_NO_DESCRIPTION
    if len(description) > PREVIEW_DESCRIPTION:
        description = description[:PREVIEW_DESCRIPTION].rstrip() + "…"
    text = texts.ADD_PREVIEW.format(
        title=data.get("title") or texts.ADD_PREVIEW_NONE,
        when=render.when(start, str(_tz(data))) if start else texts.ADD_PREVIEW_NONE,
        place=place or texts.ADD_PREVIEW_NONE,
        category=category.name if category else texts.ADD_PREVIEW_NONE,
        price=_price_label(data),
        cover=texts.ADD_PREVIEW_COVER_YES if has_cover else texts.ADD_PREVIEW_COVER_NO,
        tier=tier,
        description=description,
    )
    return text, keyboards.add_preview(EDITABLE)


async def _expired(ctx: BotContext, target: Target) -> None:
    await ctx.states.set(target.user_id, fsm.IDLE)
    await send(ctx, target, texts.ADD_EXPIRED, keyboards.menu_button())


async def on_message(
    ctx: BotContext, target: Target, state: str, text: str, image_url: str | None
) -> None:
    """Сообщение, пока открыт мастер: ответ на текущий шаг."""
    step = state.removeprefix(fsm.ADD_PREFIX)
    data = await ctx.states.get_data(target.user_id)
    if "filled" not in data:
        await _expired(ctx, target)
        return
    if step == "cover" and image_url:
        await _on_cover(ctx, target, data, image_url)
    elif step == ORG:
        await _ask_org(ctx, target, data)
    elif not text:
        await _ask(ctx, target, step, data)
    elif step in _TEXT_STEPS:
        await _TEXT_STEPS[step](ctx, target, data, text)
    else:
        # Категория и превью — кнопками.
        await _ask(ctx, target, step, data, lead=texts.ADD_BAD.get(step))


async def _on_title(ctx: BotContext, target: Target, data: dict[str, Any], text: str) -> None:
    title = " ".join(text.split())
    if not TITLE_MIN <= len(title) <= rules.TITLE_MAX:
        lead = texts.ADD_BAD["title"].format(max=rules.TITLE_MAX)
        await _ask(ctx, target, "title", data, lead=lead)
        return
    data["title"] = title
    _mark(data, "title")
    await _next(ctx, target, data, "title")


async def _on_when(ctx: BotContext, target: Target, data: dict[str, Any], text: str) -> None:
    start = parse_when(text, datetime.now(_tz(data)))
    if start is None:
        await _ask(ctx, target, "when", data, lead=texts.ADD_BAD["when"])
        return
    data["start_local"] = start.replace(tzinfo=None).isoformat("T", "minutes")
    _mark(data, "when")
    await _next(ctx, target, data, "when")


async def _on_place(ctx: BotContext, target: Target, data: dict[str, Any], text: str) -> None:
    query = text.strip()
    if len(query) < 2:
        await _ask(ctx, target, "place", data, lead=texts.LOCALITY_TOO_SHORT)
        return
    async with ctx.db() as session:
        found = await localities_service.search(session, query, OPTIONS)
    if not found:
        lead = texts.ADD_BAD["place"].format(query=query[:64])
        await _ask(ctx, target, "place", data, lead=lead)
        return
    options = [(loc.id, render.locality_label(loc)) for loc in found]
    await send(ctx, target, texts.LOCALITY_CHOOSE, keyboards.add_places(options))


async def _on_venue(ctx: BotContext, target: Target, data: dict[str, Any], text: str) -> None:
    name = " ".join(text.split())
    if not 2 <= len(name) <= 255:
        await _ask(ctx, target, "venue", data, lead=texts.ADD_BAD["venue"])
        return
    async with ctx.db() as session:
        user = await get_user(session, target)
        found = await venues_service.search(session, user, name, None)
    same_place = [v for v in found if v.locality_id == data.get("locality_id")][:OPTIONS]
    if same_place:
        data["venue_candidate"] = name
        await ctx.states.set_data(target.user_id, data)
        options = [(v.id, f"{v.name}, {v.address}" if v.address else v.name) for v in same_place]
        await send(ctx, target, texts.ADD_VENUE_FOUND, keyboards.add_venues(options, name[:60]))
        return
    # Новая площадка создаётся при отправке: отменённый мастер не оставит мусора.
    data.update(venue_id=None, venue_name=name, venue_new_name=name)
    _mark(data, "venue")
    await _next(ctx, target, data, "venue")


async def _on_price(ctx: BotContext, target: Target, data: dict[str, Any], text: str) -> None:
    hit = extract.find_price(text)
    digits = _DIGITS.match(text)
    if hit is not None:
        _set_price(data, hit.price_type, hit.price_min, hit.price_max)
    elif digits is not None and int(digits.group(1)) > 0:
        amount = Decimal(digits.group(1))
        _set_price(data, "paid", amount, amount)
    elif digits is not None:
        _set_price(data, "free")
    else:
        await _ask(ctx, target, "price", data, lead=texts.ADD_BAD["price"])
        return
    _mark(data, "price")
    await _next(ctx, target, data, "price")


async def _on_description(ctx: BotContext, target: Target, data: dict[str, Any], text: str) -> None:
    if len(text) > rules.DESCRIPTION_MAX:
        lead = texts.ADD_BAD["description"].format(max=rules.DESCRIPTION_MAX)
        await _ask(ctx, target, "description", data, lead=lead)
        return
    data["description"] = text.strip()
    _mark(data, "description")
    await _next(ctx, target, data, "description")


async def _on_cover_text(ctx: BotContext, target: Target, data: dict[str, Any], _: str) -> None:
    await _ask(ctx, target, "cover", data, lead=texts.ADD_BAD["cover"])


async def _on_preview_text(ctx: BotContext, target: Target, data: dict[str, Any], _: str) -> None:
    await _ask(ctx, target, "preview", data, lead=texts.ADD_BAD["preview"])


_TEXT_STEPS = {
    "title": _on_title,
    "when": _on_when,
    "place": _on_place,
    "venue": _on_venue,
    "price": _on_price,
    "description": _on_description,
    "cover": _on_cover_text,
    "preview": _on_preview_text,
}


async def _on_cover(ctx: BotContext, target: Target, data: dict[str, Any], url: str) -> None:
    try:
        raw = await ctx.max.download(url, media_service.MAX_BYTES)
        async with ctx.db() as session:
            user = await get_user(session, target)
            media = await media_service.upload(session, user, raw, ctx.settings.media_dir)
    except AppError as exc:
        lead = texts.ADD_COVER_FAILED.format(reason=exc.message)
        await _ask(ctx, target, "cover", data, lead=lead)
        return
    except (ValueError, OSError, httpx.HTTPError) as exc:
        log.warning("bot_cover_download_failed", error=type(exc).__name__)
        lead = texts.ADD_COVER_FAILED.format(reason=texts.ADD_COVER_UNAVAILABLE)
        await _ask(ctx, target, "cover", data, lead=lead)
        return
    data["cover_media_id"] = media.id
    _mark(data, "cover")
    await send(ctx, target, texts.ADD_COVER_SAVED)
    await _next(ctx, target, data, "cover")


# --- Кнопки ------------------------------------------------------------------------------


async def on_callback(ctx: BotContext, target: Target, args: list[str], answer: Answer) -> None:
    """Кнопки add:<действие>[:<аргумент>]."""
    await answer()
    state = await ctx.states.get(target.user_id)
    data = await ctx.states.get_data(target.user_id)
    if not is_active(state) or "filled" not in data:
        await _expired(ctx, target)
        return
    step = state.removeprefix(fsm.ADD_PREFIX)
    action = args[0] if args else ""
    arg = args[1] if len(args) > 1 else None

    if action == "cancel":
        await ctx.states.set(target.user_id, fsm.IDLE)
        await send(ctx, target, texts.ADD_CANCELLED, keyboards.menu_button())
    elif action == "back":
        await _back(ctx, target, step, data)
    elif action == "org" and step == ORG and arg is not None:
        orgs = data.get("orgs", {})
        if arg in orgs:
            data.update(org_id=int(arg), org_name=orgs[arg])
        await _ask(ctx, target, "title", data, lead=texts.ADD_START)
    elif action == "skip" and step in OPTIONAL:
        for key in _SKIP_KEYS[step]:
            data.pop(key, None)
        _mark(data, step)
        await _next(ctx, target, data, step)
    elif action == "loc" and step == "place" and arg is not None and arg.isdigit():
        await _choose_place(ctx, target, data, int(arg))
    elif action == "venue" and step == "venue" and arg is not None:
        await _choose_venue(ctx, target, data, arg)
    elif action == "cat" and step == "category" and arg is not None and is_known(arg):
        data["category"] = arg
        _mark(data, "category")
        await _next(ctx, target, data, "category")
    elif action == "price" and step == "price" and arg in ("free", "donation"):
        _set_price(data, arg)
        _mark(data, "price")
        await _next(ctx, target, data, "price")
    elif action == "edit" and step == "preview" and arg in EDITABLE:
        data["editing"] = True
        await _ask(ctx, target, arg, data)
    elif action == "send" and step == "preview":
        await _submit(ctx, target, data)
    else:
        # Кнопка от прошлого шага: повторяем текущий.
        await _repeat(ctx, target, step, data)


async def _repeat(ctx: BotContext, target: Target, step: str, data: dict[str, Any]) -> None:
    if step == ORG:
        await _ask_org(ctx, target, data)
    else:
        await _ask(ctx, target, step, data)


async def _back(ctx: BotContext, target: Target, step: str, data: dict[str, Any]) -> None:
    data.pop("editing", None)
    if step not in STEPS or step == "title":
        # С первого шага назад некуда: выбор организации, если он был, иначе снова название.
        if data.get("orgs"):
            await _save(ctx, target, ORG, data)
            await _ask_org(ctx, target, data)
        else:
            await _ask(ctx, target, "title", data)
        return
    await _ask(ctx, target, STEPS[STEPS.index(step) - 1], data)


async def _choose_place(
    ctx: BotContext, target: Target, data: dict[str, Any], locality_id: int
) -> None:
    async with ctx.db() as session:
        locality = await localities_service.get_out(session, locality_id)
    if locality is None:
        await _ask(ctx, target, "place", data)
        return
    if data.get("locality_id") != locality.id:
        # Площадка другого пункта больше не подходит.
        for key in _SKIP_KEYS["venue"]:
            data.pop(key, None)
        if "venue" in data["filled"]:
            data["filled"].remove("venue")
    data.update(locality_id=locality.id, locality_name=locality.name, tz=locality.timezone)
    _mark(data, "place")
    await _next(ctx, target, data, "place")


async def _choose_venue(ctx: BotContext, target: Target, data: dict[str, Any], arg: str) -> None:
    if arg == "new" and data.get("venue_candidate"):
        name = data.pop("venue_candidate")
        data.update(venue_id=None, venue_name=name, venue_new_name=name)
    elif arg.isdigit():
        async with ctx.db() as session:
            venue = await venues_service.get_out(session, int(arg))
        if venue is None or venue.locality_id != data.get("locality_id"):
            await _ask(ctx, target, "venue", data)
            return
        data.pop("venue_new_name", None)
        data.update(venue_id=venue.id, venue_name=venue.name)
    else:
        await _ask(ctx, target, "venue", data)
        return
    _mark(data, "venue")
    await _next(ctx, target, data, "venue")


# --- Отправка ----------------------------------------------------------------------------


def _step_for(exc: AppError) -> str | None:
    for item in exc.details.get("fields") or []:
        step = _FIELD_STEPS.get(str(item.get("field", "")).split(".")[0])
        if step:
            return step
    return None


def _fields(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": data["title"],
        "category": data["category"],
        "locality_id": data["locality_id"],
        "venue_id": data.get("venue_id"),
        "price_type": data["price_type"],
        "price_min": data.get("price_min"),
        "price_max": data.get("price_max"),
        "description": data.get("description"),
        "cover_media_id": data.get("cover_media_id"),
        "sessions": [{"starts_at": _start(data)}],
    }


async def _submit(ctx: BotContext, target: Target, data: dict[str, Any]) -> None:
    missing = next((s for s in REQUIRED if s not in data["filled"]), None)
    if missing is not None:
        await _ask(ctx, target, missing, data)
        return
    try:
        async with ctx.db() as session:
            user = await get_user(session, target)
            notifier = _ExceptAuthor(notifier_of(ctx), user.id)
            if data.get("venue_new_name"):
                venue = await venues_service.create(
                    session,
                    user,
                    VenueIn(name=data["venue_new_name"], locality_id=data["locality_id"]),
                )
                data.pop("venue_new_name")
                data["venue_id"] = venue.id
                await ctx.states.set_data(target.user_id, data)
            fields = _fields(data)
            if data.get("event_id"):
                event = await event_editor.patch(
                    session,
                    user,
                    data["event_id"],
                    EventPatch.model_validate(fields),
                    jobs=ctx.jobs,
                    notifier=notifier,
                )
            else:
                body = EventCreate.model_validate({**fields, "organization_id": data["org_id"]})
                event = await event_editor.create(session, user, body)
                # Повторная отправка после отказа правит то же событие, а не плодит новые.
                data["event_id"] = event.id
                await ctx.states.set_data(target.user_id, data)
            event = await event_editor.submit(
                session, user, event.id, jobs=ctx.jobs, notifier=notifier
            )
            event_id, title = event.id, event.title
            status, reason = event.status, event.moderation_reason
    except AppError as exc:
        log.info("bot_add_submit_failed", code=exc.code)
        if exc.status_code == 404:
            data.pop("event_id", None)
        step = _step_for(exc) or "preview"
        await _ask(ctx, target, step, data, lead=texts.ADD_FIX_FIELD.format(message=exc.message))
        return

    if status == EventStatus.rejected:
        # Правила §6 отклонили содержимое: черновик остаётся, можно исправить и отправить снова.
        lead = texts.ADD_SENT_REJECTED.format(title=title, reason=reason or "—")
        await _ask(ctx, target, "preview", data, lead=lead)
        return
    await ctx.states.set(target.user_id, fsm.IDLE)
    keyboard = keyboards.app_and_menu(
        texts.ADD_OPEN_APP, await ctx.web_app_name(), event_deeplink(event_id, status)
    )
    await send(ctx, target, texts.ADD_SENT_PENDING.format(title=title), keyboard)
