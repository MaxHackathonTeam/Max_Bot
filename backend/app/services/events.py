"""Лента и карточка события (FR-CAT, FR-EV).

Лента — события с ближайшим подходящим сеансом (FR-CAT-1), только `published` и только
с будущими сеансами (FR-CAT-7). Ленты `official` и `community` не смешиваются: демо-события
с организацией попадают в «Официальные», без организации — в «От сообщества», и всегда
остаются помечены `is_demo`.
"""

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Numeric,
    and_,
    cast,
    func,
    literal,
    or_,
    select,
    text,
    true,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import EventStatus, PriceType, SessionStatus, TrustTier, VerificationStatus
from app.models.events import Event, EventSession, EventSource
from app.models.geo import Locality, Venue
from app.models.orgs import Organization
from app.schemas.events import (
    EventCard,
    EventDetail,
    EventPage,
    LocalityBrief,
    OrgBrief,
    SessionOut,
    SourceInfo,
    VenueBrief,
)
from app.services.localities import DEFAULT_TIMEZONE, geo_point, lat_of, lon_of, timezone_for

DatePreset = Literal["today", "tomorrow", "weekend"]
Tier = Literal["official", "community", "all"]
Format = Literal["all", "offline", "online"]
Sort = Literal["date", "distance", "relevance"]

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
RADIUS_CHOICES = (5, 15, 30, 50)
TYPO_THRESHOLD = 0.45
# По прямой ссылке видны и прошедшие/отменённые, но не черновики и не скрытые.
PUBLIC_STATUSES = (EventStatus.published, EventStatus.cancelled, EventStatus.archived)

_SOURCE_LABELS = {
    "organizer": "Организатор",
    "community": "Житель, от сообщества",
    "demo": "Демо-данные",
}


@dataclass
class EventFilters:
    locality_id: int | None = None
    lat: float | None = None
    lon: float | None = None
    radius_km: int = 30
    date_preset: DatePreset | None = None
    date_from: date | None = None
    date_to: date | None = None
    # Час начала «не раньше» в часовом поясе точки поиска («после 18»).
    time_from: int | None = None
    categories: list[str] = field(default_factory=list)
    free: bool = False
    price_max: int | None = None
    pushkin: bool = False
    age: int | None = None
    tier: Tier = "official"
    format: Format = "all"
    q: str | None = None
    sort: Sort | None = None
    cursor: str | None = None
    limit: int = DEFAULT_LIMIT
    include_total: bool = False


@dataclass(frozen=True)
class Origin:
    lat: float
    lon: float
    timezone: str


# --- Вспомогательное -----------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(UTC)


def share_url(bot_username: str, event_id: int) -> str | None:
    """Диплинк на карточку в мини-аппе (§3.1); без имени бота ссылку не собрать."""
    if not bot_username:
        return None
    return f"https://max.ru/{bot_username}?startapp=ev_{event_id}"


def map_url(lat: float, lon: float) -> str:
    return f"https://yandex.ru/maps/?pt={lon:.6f},{lat:.6f}&z=16"


def tier_condition(tier: Tier) -> ColumnElement[bool]:
    demo = Event.trust_tier == TrustTier.demo
    if tier == "official":
        return or_(
            Event.trust_tier == TrustTier.official,
            and_(demo, Event.organization_id.is_not(None)),
        )
    if tier == "community":
        return or_(
            Event.trust_tier == TrustTier.community,
            and_(demo, Event.organization_id.is_(None)),
        )
    return true()


def date_range(
    filters: EventFilters, tz_name: str, now: datetime
) -> tuple[datetime | None, datetime | None]:
    """Границы [начало, конец) в часовом поясе точки поиска."""
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()

    def at(d: date) -> datetime:
        return datetime.combine(d, time(), tzinfo=tz)

    if filters.date_preset == "today":
        return at(today), at(today + timedelta(days=1))
    if filters.date_preset == "tomorrow":
        return at(today + timedelta(days=1)), at(today + timedelta(days=2))
    if filters.date_preset == "weekend":
        weekday = today.weekday()
        start = today if weekday >= 5 else today + timedelta(days=5 - weekday)
        monday = today + timedelta(days=7 - weekday)
        return at(start), at(monday)
    start_at = at(filters.date_from) if filters.date_from else None
    end_at = at(filters.date_to + timedelta(days=1)) if filters.date_to else None
    return start_at, end_at


async def resolve_origin(session: AsyncSession, filters: EventFilters) -> Origin | None:
    if filters.lat is not None and filters.lon is not None:
        return Origin(filters.lat, filters.lon, timezone_for(filters.lat, filters.lon))
    if filters.locality_id is None:
        return None
    row = (
        await session.execute(
            select(lat_of(Locality.point), lon_of(Locality.point), Locality.timezone).where(
                Locality.id == filters.locality_id
            )
        )
    ).first()
    if row is None:
        raise AppError("locality_not_found", "Населённый пункт не найден", status_code=404)
    return Origin(row[0], row[1], row[2])


def _encode_cursor(sort: Sort, key: Sequence[Any]) -> str:
    values = [v.isoformat() if isinstance(v, datetime) else v for v in key]
    values = [str(v) if isinstance(v, Decimal) else v for v in values]
    raw = json.dumps({"s": sort, "k": values}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, sort: Sort) -> list[Any]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        if data["s"] != sort or not isinstance(data["k"], list):
            raise ValueError
        key: list[Any] = data["k"]
        if sort == "date":
            return [datetime.fromisoformat(key[0]), int(key[1])]
        if sort == "distance":
            return [float(key[0]), int(key[1])]
        return [Decimal(key[0]), int(key[1])]
    except (binascii.Error, ValueError, KeyError, IndexError, TypeError) as exc:
        raise AppError(
            "invalid_cursor", "Некорректный курсор, обнови ленту", status_code=400
        ) from exc


# --- Лента ---------------------------------------------------------------------------


async def search(
    session: AsyncSession, filters: EventFilters, now: datetime | None = None
) -> EventPage:
    now = now or utcnow()
    limit = max(1, min(filters.limit, MAX_LIMIT))
    # Запрос ленты короткий, но на 10k событий оценка стоимости выше jit_above_cost:
    # компиляция JIT добавляет десятки мс и даёт выбросы до секунды.
    await session.execute(text("SET LOCAL jit = off"))
    origin = await resolve_origin(session, filters)
    q = (filters.q or "").strip()
    sort: Sort = filters.sort or ("relevance" if q else "date")
    if sort == "relevance" and not q:
        sort = "date"
    if sort == "distance" and origin is None:
        sort = "date"

    range_start, range_end = date_range(
        filters, origin.timezone if origin else DEFAULT_TIMEZONE, now
    )
    lower = max(now, range_start) if range_start else now
    session_conds: list[ColumnElement[bool]] = [
        EventSession.event_id == Event.id,
        EventSession.status == SessionStatus.scheduled,
        func.coalesce(EventSession.ends_at, EventSession.starts_at) >= lower,
    ]
    if range_end is not None:
        session_conds.append(EventSession.starts_at < range_end)
    if filters.time_from is not None:
        tz_name = origin.timezone if origin else DEFAULT_TIMEZONE
        local_start = func.timezone(tz_name, EventSession.starts_at)
        session_conds.append(func.extract("hour", local_start) >= filters.time_from)
    next_session = (
        select(
            EventSession.id.label("id"),
            EventSession.starts_at.label("starts_at"),
            EventSession.ends_at.label("ends_at"),
            EventSession.status.label("status"),
        )
        .where(*session_conds)
        .order_by(EventSession.starts_at, EventSession.id)
        .limit(1)
        .lateral("ns")
    )

    place_point = func.coalesce(Venue.point, Locality.point)
    distance_m: ColumnElement[Any] = literal(None)
    conds: list[ColumnElement[bool]] = [
        Event.status == EventStatus.published,
        tier_condition(filters.tier),
    ]
    if origin is not None:
        origin_point = geo_point(origin.lat, origin.lon)
        distance_m = func.ST_Distance(place_point, origin_point)
        within = func.ST_DWithin(place_point, origin_point, filters.radius_km * 1000)
        # Онлайн-события без площадки не привязаны к месту — показываем их везде.
        conds.append(or_(within, and_(Event.is_online, place_point.is_(None))))
    if filters.format == "offline":
        conds.append(Event.is_online.is_(False))
    elif filters.format == "online":
        conds.append(Event.is_online.is_(True))
    if filters.categories:
        conds.append(Event.category.in_(filters.categories))
    if filters.free:
        conds.append(Event.price_type == PriceType.free)
    elif filters.price_max is not None:
        conds.append(
            or_(
                Event.price_type == PriceType.free,
                and_(
                    Event.price_type.in_((PriceType.paid, PriceType.donation)),
                    func.coalesce(Event.price_min, 0) <= filters.price_max,
                ),
            )
        )
    if filters.pushkin:
        conds.append(Event.pushkin_card.is_(True))
    if filters.age is not None:
        conds.append(or_(Event.age_rating.is_(None), Event.age_rating <= filters.age))

    rank: ColumnElement[Any] = literal(None)
    if q:
        # По умолчанию порог 0.6 — одна опечатка в коротком слове его не проходит.
        await session.execute(
            text(f"SET LOCAL pg_trgm.word_similarity_threshold = {TYPO_THRESHOLD}")
        )
        tsquery = func.websearch_to_tsquery("russian", q)
        conds.append(or_(Event.search_tsv.op("@@")(tsquery), Event.title.op("%>")(q)))
        rank = func.round(
            cast(
                func.ts_rank(Event.search_tsv, tsquery) + func.word_similarity(q, Event.title),
                Numeric,
            ),
            6,
        )

    base = (
        select(Event.id)
        .select_from(Event)
        .join(next_session, true())
        .outerjoin(Venue, Venue.id == Event.venue_id)
        .outerjoin(Locality, Locality.id == func.coalesce(Event.locality_id, Venue.locality_id))
        .where(*conds)
    )

    total: int | None = None
    if filters.include_total:
        total = await session.scalar(select(func.count()).select_from(base.subquery()))

    event_id: ColumnElement[int] = Event.id.expression
    if sort == "date":
        key_cols: list[ColumnElement[Any]] = [next_session.c.starts_at, event_id]
        order = [next_session.c.starts_at, event_id]
    elif sort == "distance":
        key_cols = [distance_m, event_id]
        order = [distance_m, event_id]
    else:
        key_cols = [rank, event_id]
        order = [rank.desc(), event_id]

    stmt = (
        base.add_columns(
            next_session.c.starts_at.label("session_starts_at"),
            next_session.c.ends_at.label("session_ends_at"),
            next_session.c.status.label("session_status"),
            next_session.c.id.label("session_id"),
            distance_m.label("distance_m"),
            rank.label("rank"),
        )
        .order_by(*order)
        .limit(limit + 1)
    )
    if filters.cursor:
        after = _decode_cursor(filters.cursor, sort)
        if sort == "relevance":
            stmt = stmt.where(or_(rank < after[0], and_(rank == after[0], Event.id > after[1])))
        else:
            stmt = stmt.where(tuple_(*key_cols) > tuple_(*after))

    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_sessions = {
        row[0]: SessionOut(
            id=row.session_id,
            starts_at=row.session_starts_at,
            ends_at=row.session_ends_at,
            status=row.session_status,
        )
        for row in rows
    }
    distances = {row[0]: row.distance_m for row in rows}
    cards = await build_cards(session, [row[0] for row in rows], next_sessions, distances, now)

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        key: list[Any] = {
            "date": [last.session_starts_at, last[0]],
            "distance": [last.distance_m, last[0]],
            "relevance": [last.rank, last[0]],
        }[sort]
        next_cursor = _encode_cursor(sort, key)
    return EventPage(items=cards, next_cursor=next_cursor, total=total)


async def _future_session_counts(
    session: AsyncSession, event_ids: Sequence[int], now: datetime
) -> dict[int, int]:
    if not event_ids:
        return {}
    rows = await session.execute(
        select(EventSession.event_id, func.count())
        .where(
            EventSession.event_id.in_(event_ids),
            EventSession.status == SessionStatus.scheduled,
            func.coalesce(EventSession.ends_at, EventSession.starts_at) >= now,
        )
        .group_by(EventSession.event_id)
    )
    return {event_id: count for event_id, count in rows.tuples()}


def _card_select() -> Any:
    return (
        select(
            Event,
            Venue,
            Locality,
            Organization,
            lat_of(func.coalesce(Venue.point, Locality.point)).label("lat"),
            lon_of(func.coalesce(Venue.point, Locality.point)).label("lon"),
        )
        .outerjoin(Venue, Venue.id == Event.venue_id)
        .outerjoin(Locality, Locality.id == func.coalesce(Event.locality_id, Venue.locality_id))
        .outerjoin(Organization, Organization.id == Event.organization_id)
    )


def _card(
    event: Event,
    venue: Venue | None,
    locality: Locality | None,
    org: Organization | None,
    *,
    next_session: SessionOut | None,
    sessions_count: int,
    distance_m: float | None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "short_description": event.short_description,
        "category": event.category,
        "cover_url": event.cover_url,
        "trust_tier": event.trust_tier,
        "is_demo": event.trust_tier == TrustTier.demo,
        "org": (
            OrgBrief(
                id=org.id,
                name=org.name,
                verified=org.verification_status == VerificationStatus.verified,
            )
            if org
            else None
        ),
        "venue": (
            VenueBrief(id=venue.id, name=venue.name, address=venue.address, lat=lat, lon=lon)
            if venue
            else None
        ),
        "locality": LocalityBrief(id=locality.id, name=locality.name) if locality else None,
        "timezone": locality.timezone if locality else DEFAULT_TIMEZONE,
        "next_session": next_session,
        "sessions_count": sessions_count,
        "distance_km": round(distance_m / 1000, 1) if distance_m is not None else None,
        "price_type": event.price_type,
        "price_min": event.price_min,
        "price_max": event.price_max,
        "pushkin_card": event.pushkin_card,
        "age_rating": event.age_rating,
        "is_online": event.is_online,
    }


async def build_cards(
    session: AsyncSession,
    event_ids: Sequence[int],
    next_sessions: dict[int, SessionOut],
    distances: dict[int, float | None],
    now: datetime,
) -> list[EventCard]:
    """Карточки в порядке `event_ids`; сеанс и расстояние считаны заранее запросом ленты."""
    if not event_ids:
        return []
    rows = (await session.execute(_card_select().where(Event.id.in_(event_ids)))).all()
    by_id = {row[0].id: row for row in rows}
    counts = await _future_session_counts(session, event_ids, now)
    cards = []
    for event_id in event_ids:
        event, venue, locality, org, lat, lon = by_id[event_id]
        cards.append(
            EventCard(
                **_card(
                    event,
                    venue,
                    locality,
                    org,
                    next_session=next_sessions.get(event_id),
                    sessions_count=counts.get(event_id, 0),
                    distance_m=distances.get(event_id),
                    lat=lat if venue else None,
                    lon=lon if venue else None,
                )
            )
        )
    return cards


# --- Карточка ------------------------------------------------------------------------


async def _source_info(session: AsyncSession, event: Event) -> SourceInfo:
    source = await session.scalar(
        select(EventSource).where(EventSource.event_id == event.id).order_by(EventSource.id)
    )
    if event.trust_tier == TrustTier.demo or (source is not None and source.source == "demo"):
        code = "demo"
    elif event.trust_tier == TrustTier.community:
        code = "community"
    else:
        code = "organizer"
    return SourceInfo(
        code=code,
        label=_SOURCE_LABELS[code],
        url=source.source_url if source is not None else None,
        updated_at=event.updated_at,
    )


async def get_detail(
    session: AsyncSession,
    event_id: int,
    *,
    origin: Origin | None = None,
    saved_session_ids: Sequence[int] = (),
    bot_username: str = "",
    now: datetime | None = None,
) -> EventDetail:
    now = now or utcnow()
    distance: ColumnElement[Any] = literal(None)
    if origin is not None:
        distance = func.ST_Distance(
            func.coalesce(Venue.point, Locality.point), geo_point(origin.lat, origin.lon)
        )
    row = (
        await session.execute(
            _card_select()
            .add_columns(distance.label("distance_m"))
            .where(Event.id == event_id, Event.status.in_(PUBLIC_STATUSES))
        )
    ).first()
    if row is None:
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    event, venue, locality, org, lat, lon, distance_m = row

    sessions = (
        await session.scalars(
            select(EventSession)
            .where(EventSession.event_id == event.id)
            .order_by(EventSession.starts_at, EventSession.id)
        )
    ).all()
    future = [s for s in sessions if (s.ends_at or s.starts_at) >= now]
    upcoming = [s for s in future if s.status == SessionStatus.scheduled]
    shown = future or list(sessions[-1:])
    is_past = event.status == EventStatus.archived or not upcoming

    def out(s: EventSession) -> SessionOut:
        return SessionOut(id=s.id, starts_at=s.starts_at, ends_at=s.ends_at, status=s.status)

    base = _card(
        event,
        venue,
        locality,
        org,
        next_session=out(upcoming[0]) if upcoming else None,
        sessions_count=len(upcoming),
        distance_m=distance_m,
        lat=lat if venue else None,
        lon=lon if venue else None,
    )
    own_ids = {s.id for s in sessions}
    return EventDetail(
        **base,
        description=event.description,
        tags=list(event.tags or []),
        sessions=[out(s) for s in shown],
        map_url=map_url(lat, lon) if lat is not None and lon is not None else None,
        online_url=event.online_url,
        ticket_url=event.ticket_url,
        registration_required=event.registration_required,
        contacts=event.contacts,
        accessibility=event.accessibility,
        indoor=event.indoor,
        source=await _source_info(session, event),
        ai_fields=list(event.ai_fields or []),
        status=event.status,
        is_past=is_past,
        saved_session_ids=[sid for sid in saved_session_ids if sid in own_ids],
        share_url=share_url(bot_username, event.id),
    )
