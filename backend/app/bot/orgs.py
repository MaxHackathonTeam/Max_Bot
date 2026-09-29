"""Профиль организации в боте: «Об организаторе», её афиши и поиск организаций (/orgs).

Данные — из того же сервиса, что открытый API (`services/org_public.py`): только публичные
поля, отозванные организации скрыты, ленты «Официальные» и «От сообщества» не смешиваются.
Колбэки — `orgp:*` (см. keyboards.P_ORG_PUBLIC), состояние ввода названия — fsm.ORG_SEARCH.
"""

from collections.abc import Sequence

import structlog

from app.bot import fsm, keyboards, render, texts
from app.bot.core import Answer, BotContext, Target, send
from app.core.errors import AppError
from app.schemas.events import EventCard
from app.schemas.orgs import OrgPublic
from app.services import events as events_service
from app.services import org_public

log = structlog.get_logger(__name__)

SEARCH_RESULTS = 5
SEARCH_MIN = 2
EVENTS_PAGE = 5
ABOUT_MAX = 700
_TIERS: dict[str, events_service.Tier] = {"o": "official", "c": "community"}


def is_active(state: str) -> bool:
    return state == fsm.ORG_SEARCH


def feed_orgs(cards: Sequence[EventCard]) -> dict[int, int]:
    """event_id → organization_id: кнопка «Об организаторе» в строках ленты."""
    return {c.id: c.org.id for c in cards if c.org is not None}


def _about(text: str) -> str:
    text = text.strip()
    return text if len(text) <= ABOUT_MAX else text[: ABOUT_MAX - 1].rstrip() + "…"


def profile_text(org: OrgPublic) -> str:
    kind = texts.ORG_KIND_LABELS.get(org.kind, texts.ORG_KIND_LABELS["other"])
    place = org.locality.name if org.locality else texts.ORG_PROFILE_NO_PLACE
    text = texts.ORG_PROFILE.format(
        name=org.name,
        status=texts.ORG_PROFILE_VERIFIED if org.verified else texts.ORG_PROFILE_UNVERIFIED,
        place=f"{place} · {kind}",
    )
    if org.description and org.description.strip():
        text += texts.ORG_PROFILE_ABOUT.format(about=_about(org.description))
    if org.future_events:
        text += texts.ORG_PROFILE_EVENTS.format(count=org.future_events)
    else:
        text += texts.ORG_PROFILE_NO_EVENTS
    if org.is_demo:
        text += texts.ORG_PROFILE_DEMO
    return text


async def _load(ctx: BotContext, org_id: int) -> OrgPublic | None:
    async with ctx.db() as session:
        try:
            return await org_public.get_public(session, org_id)
        except AppError as exc:
            if exc.code != "org_not_found":
                raise
            return None


async def send_profile(ctx: BotContext, target: Target, org_id: int, answer: Answer) -> None:
    org = await _load(ctx, org_id)
    if org is None:
        await answer(texts.ORG_NOT_FOUND_TOAST)
        return
    await answer()
    keyboard = keyboards.org_profile(
        org.id,
        web_app=await ctx.web_app_name(),
        official=org.official_events,
        community=org.community_events,
    )
    await send(ctx, target, profile_text(org), keyboard)


async def send_events(
    ctx: BotContext,
    target: Target,
    org_id: int,
    tier_code: str,
    offset: int,
    cursor: str | None,
    answer: Answer,
) -> None:
    org = await _load(ctx, org_id)
    if org is None:
        await answer(texts.ORG_NOT_FOUND_TOAST)
        return
    tier = _TIERS[tier_code]
    async with ctx.db() as session:
        try:
            page = await org_public.public_events(
                session, org_id, tier=tier, cursor=cursor, limit=EVENTS_PAGE
            )
        except AppError as exc:
            if exc.code != "invalid_cursor":
                raise
            await answer(texts.FEED_EXPIRED_TOAST)
            return
    await answer()
    other_code = "c" if tier_code == "o" else "o"
    other_count = org.community_events if other_code == "c" else org.official_events
    if not page.items:
        text = texts.ORG_EVENTS_EMPTY.format(name=org.name)
    else:
        place = org.locality.name if org.locality else texts.ORG_PROFILE_NO_PLACE
        title = texts.ORG_EVENTS_TITLE.format(name=org.name)
        text = render.feed(title, place, None, page.items, offset, tier=tier)
    keyboard = keyboards.org_events(
        await ctx.web_app_name(),
        [(c.id, c.next_session.id if c.next_session else None) for c in page.items],
        org_id=org.id,
        tier=tier_code,
        next_cursor=page.next_cursor,
        offset=offset,
        other=(other_code, other_count),
    )
    await send(ctx, target, text, keyboard)


async def begin_search(ctx: BotContext, target: Target, query: str | None = None) -> None:
    """/orgs [название] или кнопка «Найти организацию»."""
    if query:
        await on_message(ctx, target, query)
        return
    await ctx.states.set(target.user_id, fsm.ORG_SEARCH)
    await send(ctx, target, texts.ORG_SEARCH_PROMPT, keyboards.menu_button())


async def on_message(ctx: BotContext, target: Target, text: str) -> None:
    query = " ".join(text.split())
    if len(query) < SEARCH_MIN:
        await ctx.states.set(target.user_id, fsm.ORG_SEARCH)
        await send(ctx, target, texts.ORG_SEARCH_SHORT.format(min=SEARCH_MIN))
        return
    await ctx.states.set(target.user_id, fsm.IDLE)
    async with ctx.db() as session:
        page = await org_public.search(session, q=query, limit=SEARCH_RESULTS)
    log.info("bot_org_search", results=len(page.items))
    if not page.items:
        await send(
            ctx,
            target,
            texts.ORG_SEARCH_EMPTY.format(query=query[: org_public.MAX_QUERY]),
            keyboards.org_search_results([]),
        )
        return
    options = [
        (
            item.id,
            ("✅ " if item.verified else "")
            + item.name
            + (f" · {item.locality.name}" if item.locality else ""),
        )
        for item in page.items
    ]
    await send(ctx, target, texts.ORG_SEARCH_RESULTS, keyboards.org_search_results(options))


async def on_callback(ctx: BotContext, target: Target, args: list[str], answer: Answer) -> None:
    """orgp:<id> | orgp:ev:<id>:<o|c>:<offset>[:<cursor>] | orgp:find."""
    if args == ["find"]:
        await answer()
        await begin_search(ctx, target)
    elif len(args) == 1 and args[0].isdigit():
        await send_profile(ctx, target, int(args[0]), answer)
    elif (
        len(args) in (4, 5)
        and args[0] == "ev"
        and args[1].isdigit()
        and args[2] in _TIERS
        and args[3].isdigit()
    ):
        cursor = args[4] if len(args) == 5 else None
        await send_events(ctx, target, int(args[1]), args[2], int(args[3]), cursor, answer)
    else:
        log.info("bot_unknown_org_callback", args=len(args))
        await answer(texts.FEED_EXPIRED_TOAST)
