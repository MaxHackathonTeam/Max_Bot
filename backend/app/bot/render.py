"""Тексты сообщений бота из данных: подборки, «Пойду», настройки. Только форматирование."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.bot import texts
from app.models.users import User
from app.schemas.events import EventCard, SavedItem, SessionOut
from app.schemas.geo import LocalityOut
from app.schemas.manage import MyEventItem
from app.services.categories import BY_SLUG


def when(starts_at: datetime, tz_name: str) -> str:
    """Время в часовом поясе населённого пункта события."""
    local = starts_at.astimezone(ZoneInfo(tz_name))
    return texts.WHEN.format(
        weekday=texts.WEEKDAYS[local.weekday()],
        date=local.strftime("%d.%m"),
        time=local.strftime("%H:%M"),
    )


def _rub(value: Decimal) -> str:
    return f"{value:,.0f}".replace(",", " ")


def price(card: EventCard) -> str:
    if card.price_type == "free":
        return texts.PRICE_FREE
    if card.price_type == "donation":
        return texts.PRICE_DONATION
    if card.price_min is None:
        return texts.PRICE_UNKNOWN
    if card.price_max is not None and card.price_max != card.price_min:
        return texts.PRICE_FROM.format(price=_rub(card.price_min))
    return texts.PRICE_EXACT.format(price=_rub(card.price_min))


def _place(card: EventCard) -> str:
    parts = [card.venue.name] if card.venue else []
    if card.locality:
        parts.append(card.locality.name)
    return ", ".join(parts) or "—"


def _item(n: int, card: EventCard, session: SessionOut | None) -> str:
    distance = ""
    if card.distance_km is not None:
        km = f"{card.distance_km:.0f}" if card.distance_km >= 1 else "<1"
        distance = texts.DISTANCE.format(km=km)
    return texts.FEED_ITEM.format(
        n=n,
        when=when(session.starts_at, card.timezone) if session else "—",
        title=card.title,
        demo=texts.FEED_ITEM_DEMO if card.is_demo else "",
        place=_place(card),
        distance=distance,
        price=price(card),
        pushkin=texts.PUSHKIN_MARK if card.pushkin_card else "",
    )


def feed(
    title: str,
    place: str,
    radius: int | None,
    cards: Sequence[EventCard],
    offset: int = 0,
    *,
    tier: str = "official",
) -> str:
    """Одна лента доверия (official или community): ленты не смешиваются."""
    tier_label = texts.FEED_TIERS[tier]
    header = (
        texts.FEED_HEADER.format(tier=tier_label, title=title, place=place, radius=radius)
        if radius is not None
        else texts.FEED_HEADER_SEARCH.format(tier=tier_label, title=title, place=place)
    )
    lines = [header, ""]
    lines += [_item(n, c, c.next_session) for n, c in enumerate(cards, start=offset + 1)]
    if any(c.is_demo for c in cards):
        lines += ["", texts.FEED_DEMO_NOTE]
    return "\n".join(lines)


def saved(items: Sequence[SavedItem]) -> str:
    lines = [texts.SAVED_HEADER, ""]
    lines += [_item(n, i.event, i.session) for n, i in enumerate(items, start=1)]
    if any(i.event.is_demo for i in items):
        lines += ["", texts.FEED_DEMO_NOTE]
    return "\n".join(lines)


def locality_label(locality: LocalityOut) -> str:
    """«Ёлкино, Шимский район, Новгородская область» — тёзки различаются районом и регионом."""
    parts = [locality.name]
    parts += [p for p in (locality.municipality, locality.region) if p and p != locality.name]
    return ", ".join(dict.fromkeys(parts))


def my_events(items: Sequence[MyEventItem]) -> str:
    lines = [texts.MY_HEADER, ""]
    for n, item in enumerate(items, start=1):
        reason = (
            texts.MY_REASON.format(reason=item.moderation_reason)
            if item.moderation_reason and item.status in ("rejected", "hidden", "pending")
            else ""
        )
        lines.append(
            texts.MY_ITEM.format(
                n=n,
                title=item.title or "—",
                status=texts.MY_STATUSES.get(item.status, item.status),
                when=(
                    f" · {when(item.next_starts_at, item.timezone)}" if item.next_starts_at else ""
                ),
                reason=reason,
            )
        )
    return "\n".join(lines)


def settings(user: User, place: str | None) -> str:
    names = [BY_SLUG[s].name for s in user.interests or [] if s in BY_SLUG]
    return texts.SETTINGS.format(
        place=place or texts.SETTINGS_NO_PLACE,
        radius=user.radius_km,
        interests=", ".join(names) or texts.SETTINGS_NO_INTERESTS,
        reminders=texts.SETTINGS_ON if user.notify_reminders else texts.SETTINGS_OFF,
        digest=texts.SETTINGS_ON if user.notify_digest else texts.SETTINGS_OFF,
    )
