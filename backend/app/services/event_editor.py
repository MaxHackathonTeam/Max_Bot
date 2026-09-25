"""Создание и управление событиями (FR-PUB-1, 3, 4, 5): права, статусы, лимиты, trust_tier.

Переходы: draft → pending → published | rejected; published → cancelled | hidden | archived.
Официальные события публикуются сразу (постмодерация), события сообщества — после LLM.
"""

import hashlib
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.core.errors import AppError
from app.core.jobs import MODERATE_EVENT, JobQueue
from app.models.enums import EventStatus, PriceType, SessionStatus, TrustTier
from app.models.events import Event, EventSession, EventSource, Media, SavedSession
from app.models.geo import Locality, Venue
from app.models.orgs import Organization
from app.models.users import User
from app.moderation import rules
from app.schemas.events import SessionOut, VenueBrief
from app.schemas.manage import EventCreate, EventFields, EventManage, MyEventItem, SessionIn
from app.services import audit
from app.services import media as media_service
from app.services import moderation as moderation_service
from app.services import notifications as notifications_service
from app.services import orgs as orgs_service
from app.services import users as users_service
from app.services import venues as venues_service
from app.services.categories import is_known
from app.services.events import utcnow
from app.services.localities import DEFAULT_TIMEZONE
from app.services.notify import Notifier

DAILY_LIMIT = 10
COMMUNITY_ACTIVE_LIMIT = 3
LIST_LIMIT = 100

# Поля формы, которые копируются в модель как есть.
_PLAIN_FIELDS = (
    "title",
    "description",
    "short_description",
    "category",
    "tags",
    "cover_media_id",
    "venue_id",
    "locality_id",
    "is_online",
    "online_url",
    "indoor",
    "price_type",
    "price_min",
    "price_max",
    "pushkin_card",
    "age_rating",
    "registration_required",
    "ticket_url",
    "contacts",
    "accessibility",
)
# Изменение этих полей у опубликованного события запускает повторную модерацию (FR-PUB-3).
_MODERATED_FIELDS = frozenset(
    {
        "title",
        "description",
        "short_description",
        "category",
        "tags",
        "cover_media_id",
        "venue_id",
        "locality_id",
        "is_online",
        "online_url",
        "price_type",
        "price_min",
        "price_max",
        "ticket_url",
        "contacts",
        "sessions",
    }
)
_ACTIVE = (EventStatus.pending, EventStatus.published)
_EDITABLE = (
    EventStatus.draft,
    EventStatus.pending,
    EventStatus.published,
    EventStatus.rejected,
    EventStatus.hidden,
)


def _snapshot(event: Event) -> dict[str, Any]:
    return {f: _jsonable(getattr(event, f)) for f in _PLAIN_FIELDS}


def _jsonable(value: Any) -> Any:
    if isinstance(value, list):
        return list(value)
    if value is None or isinstance(value, (bool, int, str, dict)):
        return value
    return str(value)


def _form_error(violations: list[rules.Violation]) -> AppError:
    return AppError(
        "validation_error",
        violations[0].message if len(violations) == 1 else "Проверь поля формы",
        status_code=422,
        details={
            "fields": [{"field": v.field, "code": v.code, "message": v.message} for v in violations]
        },
    )


def _one(field: str, code: str, message: str) -> AppError:
    return _form_error([rules.Violation(code, field, message)])


# --- Права -----------------------------------------------------------------------------


async def _load(session: AsyncSession, event_id: int, *, lock: bool = False) -> Event:
    event = await session.get(Event, event_id, with_for_update=lock, populate_existing=True)
    if event is None:
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    return event


async def can_manage(session: AsyncSession, user: User, event: Event) -> bool:
    if event.author_user_id == user.id:
        return True
    if event.organization_id is None:
        return False
    return await orgs_service.get_role(session, event.organization_id, user.id) is not None


async def _require_manage(
    session: AsyncSession, user: User, event_id: int, *, lock: bool = False
) -> Event:
    event = await _load(session, event_id, lock=lock)
    if not await can_manage(session, user, event):
        raise AppError("forbidden", "Это событие может менять только его автор или команда", 403)
    return event


async def _tier_for(session: AsyncSession, user: User, org_id: int | None) -> TrustTier:
    """official — только от проверенной организации, в которой состоит пользователь (§5.2)."""
    if org_id is None:
        return TrustTier.community
    org = await session.get(Organization, org_id)
    role = await orgs_service.get_role(session, org_id, user.id)
    if org is not None and role is not None and orgs_service.is_verified(org):
        return TrustTier.official
    return TrustTier.community


# --- Поля ------------------------------------------------------------------------------


async def _check_refs(
    session: AsyncSession, user: User, event: Event, data: dict[str, Any]
) -> None:
    if data.get("category") is not None and not is_known(data["category"]):
        raise _one("category", "unknown", "Выбери категорию из списка")
    if (
        data.get("locality_id") is not None
        and await session.get(Locality, data["locality_id"]) is None
    ):
        raise _one("locality_id", "not_found", "Населённый пункт не найден")
    if data.get("venue_id") is not None:
        venue = await session.get(Venue, data["venue_id"])
        if venue is None:
            raise _one("venue_id", "not_found", "Площадка не найдена")
        if venue.org_id is not None and venue.org_id != event.organization_id:
            role = await orgs_service.get_role(session, venue.org_id, user.id)
            if role is None:
                raise _one("venue_id", "forbidden", "Это площадка другой организации")
    if data.get("cover_media_id") is not None:
        media = await session.get(Media, data["cover_media_id"])
        if media is None or (
            media.owner_user_id != user.id and data["cover_media_id"] != event.cover_media_id
        ):
            raise _one("cover_media_id", "not_found", "Обложка не найдена — загрузи её заново")


# Колонки без NULL: явный null из формы означает «не менять».
_NOT_NULL = ("is_online", "indoor", "price_type", "pushkin_card", "registration_required", "tags")


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    for key in _NOT_NULL:
        if key in data and data[key] is None:
            del data[key]
    for key in ("online_url", "ticket_url"):
        if isinstance(data.get(key), str):
            data[key] = data[key] or None
    if data.get("tags") is not None:
        data["tags"] = list(dict.fromkeys(t.strip().lower() for t in data["tags"] if t.strip()))
    for key in ("title", "description", "short_description", "contacts"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip() or None
    if "title" in data and data["title"] is None:
        data["title"] = ""
    return data


async def _apply_fields(
    session: AsyncSession, user: User, event: Event, body: EventFields
) -> set[str]:
    data = _normalize(body.model_dump(exclude_unset=True, exclude={"sessions", "organization_id"}))
    await _check_refs(session, user, event, data)
    changed: set[str] = set()
    for key, value in data.items():
        if getattr(event, key) != value:
            setattr(event, key, value)
            changed.add(key)
    if "cover_media_id" in changed:
        media = await session.get(Media, event.cover_media_id) if event.cover_media_id else None
        event.cover_url = media_service.media_url(media) if media is not None else None
    return changed


async def _sessions(session: AsyncSession, event_id: int) -> list[EventSession]:
    return list(
        await session.scalars(
            select(EventSession)
            .where(EventSession.event_id == event_id)
            .order_by(EventSession.starts_at, EventSession.id)
        )
    )


async def _apply_sessions(
    session: AsyncSession, event: Event, items: list[SessionIn]
) -> tuple[bool, set[int]]:
    """Возвращает (изменились ли, id новых или перенесённых сеансов)."""
    existing = {s.id: s for s in await _sessions(session, event.id)}
    keep: set[int] = set()
    touched: set[int] = set()
    changed = False
    for item in items:
        if item.id is not None:
            current = existing.get(item.id)
            if current is None:
                raise _one("sessions", "not_found", "Сеанс не найден — обнови страницу")
            keep.add(current.id)
            if current.starts_at != item.starts_at or current.ends_at != item.ends_at:
                current.starts_at, current.ends_at = item.starts_at, item.ends_at
                current.status = SessionStatus.scheduled
                touched.add(current.id)
                changed = True
        else:
            new = EventSession(event_id=event.id, starts_at=item.starts_at, ends_at=item.ends_at)
            session.add(new)
            await session.flush()
            touched.add(new.id)
            changed = True
    for session_id, current in existing.items():
        if session_id in keep:
            continue
        changed = True
        if event.status == EventStatus.draft:
            await session.delete(current)
        elif current.status != SessionStatus.cancelled:
            current.status = SessionStatus.cancelled
    await session.flush()
    return changed, touched


# --- Проверки при отправке -----------------------------------------------------------------


def _required(event: Event, sessions: list[EventSession]) -> list[rules.Violation]:
    found = []
    if not event.category:
        found.append(rules.Violation("required", "category", "Выбери категорию"))
    if event.venue_id is None and event.locality_id is None and not event.is_online:
        found.append(rules.Violation("required", "venue_id", "Укажи площадку или населённый пункт"))
    if event.is_online and not event.online_url:
        found.append(rules.Violation("required", "online_url", "Укажи ссылку на трансляцию"))
    if event.price_type == PriceType.unknown:
        found.append(rules.Violation("required", "price_type", "Укажи, платное ли событие"))
    if event.pushkin_card and event.trust_tier != TrustTier.official:
        found.append(
            rules.Violation(
                "pushkin_forbidden",
                "pushkin_card",
                "«Пушкинская карта» доступна только проверенным организациям",
            )
        )
    if event.age_rating is not None and event.age_rating not in (0, 6, 12, 16, 18):
        found.append(rules.Violation("bad_value", "age_rating", "Возраст: 0+, 6+, 12+, 16+, 18+"))
    return found


def _rules_data(
    event: Event, sessions: list[EventSession], fresh_ids: set[int] | None
) -> rules.EventData:
    active = [s for s in sessions if s.status != SessionStatus.cancelled]
    return rules.EventData(
        title=event.title or "",
        description=event.description,
        short_description=event.short_description,
        tags=list(event.tags or []),
        contacts=event.contacts,
        links=[u for u in (event.ticket_url, event.online_url) if u],
        sessions=[
            rules.SessionData(s.starts_at, s.ends_at, is_new=fresh_ids is None or s.id in fresh_ids)
            for s in active
        ],
        price_min=event.price_min,
        price_max=event.price_max,
    )


def content_hash(event: Event, sessions: list[EventSession]) -> str:
    first = min(
        (s.starts_at for s in sessions if s.status != SessionStatus.cancelled), default=None
    )
    parts = [
        rules._normalize(" ".join((event.title or "").split())),
        rules._normalize(" ".join((event.description or "").split())),
        first.isoformat() if first else "",
        str(event.venue_id or event.locality_id or ""),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


async def _check_limits(session: AsyncSession, user: User, event: Event, digest: str) -> None:
    duplicate = await session.scalar(
        select(Event.id).where(
            Event.id != event.id,
            Event.content_hash == digest,
            Event.author_user_id == user.id,
            Event.status.in_((*_ACTIVE, EventStatus.hidden)),
        )
    )
    if duplicate is not None:
        raise AppError(
            "duplicate",
            "Такое событие у тебя уже есть",
            status_code=409,
            details={"event_id": duplicate},
        )
    if event.trust_tier != TrustTier.community:
        return
    now = utcnow()
    future = exists().where(
        EventSession.event_id == Event.id,
        EventSession.status == SessionStatus.scheduled,
        func.coalesce(EventSession.ends_at, EventSession.starts_at) >= now,
    )
    active = await session.scalar(
        select(func.count())
        .select_from(Event)
        .where(
            Event.id != event.id,
            Event.author_user_id == user.id,
            Event.trust_tier == TrustTier.community,
            Event.status.in_(_ACTIVE),
            future,
        )
    )
    if (active or 0) >= COMMUNITY_ACTIVE_LIMIT:
        raise AppError(
            "limit_exceeded",
            f"В «От сообщества» можно держать не больше {COMMUNITY_ACTIVE_LIMIT} активных событий",
            status_code=429,
        )


async def _moderate(
    session: AsyncSession,
    user: User,
    event: Event,
    sessions: list[EventSession],
    fresh_ids: set[int] | None,
    notifier: Notifier,
) -> bool:
    """Синхронные правила. False — событие отклонено правилами (уже сохранено в сессии)."""
    violations = _required(event, sessions) + rules.check(
        _rules_data(event, sessions, fresh_ids), utcnow()
    )
    form = [v for v in violations if v.kind == "form"]
    if form:
        raise _form_error(form)
    content = [v for v in violations if v.kind == "content"]
    if content:
        await moderation_service.reject_by_rules(
            session, event, content, rules.content_reason(content)
        )
        return False
    return True


async def _after_rules_rejected(session: AsyncSession, notifier: Notifier, event: Event) -> None:
    await session.commit()
    await moderation_service.notify_owner(
        session,
        notifier,
        event,
        texts.EVENT_REJECTED.format(title=event.title, reason=event.moderation_reason),
    )


# --- Действия ---------------------------------------------------------------------------


async def create(session: AsyncSession, user: User, body: EventCreate) -> Event:
    if not await users_service.has_required_consents(session, user):
        raise AppError(
            "consent_required", "Чтобы публиковать события, прими условия и политику", 403
        )
    if body.organization_id is not None:
        await orgs_service.require_member(session, body.organization_id, user)
    since = utcnow() - timedelta(hours=24)
    today = await session.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.author_user_id == user.id, Event.created_at >= since)
    )
    if (today or 0) >= DAILY_LIMIT:
        raise AppError(
            "limit_exceeded", f"Не больше {DAILY_LIMIT} событий в сутки — продолжи завтра", 429
        )
    tier = await _tier_for(session, user, body.organization_id)
    event = Event(
        title="",
        author_user_id=user.id,
        organization_id=body.organization_id,
        trust_tier=tier,
        status=EventStatus.draft,
    )
    session.add(event)
    await session.flush()
    await _apply_fields(session, user, event, body)
    if body.sessions:
        await _apply_sessions(session, event, body.sessions)
    await audit.record(
        session,
        action="event.create",
        entity_type="event",
        entity_id=event.id,
        actor_user_id=user.id,
        diff={"organization_id": event.organization_id, "trust_tier": tier, **_snapshot(event)},
    )
    await session.commit()
    return event


async def patch(
    session: AsyncSession,
    user: User,
    event_id: int,
    body: EventFields,
    *,
    jobs: JobQueue,
    notifier: Notifier,
) -> Event:
    event = await _require_manage(session, user, event_id, lock=True)
    if event.status not in _EDITABLE:
        raise AppError("not_editable", "Отменённое или прошедшее событие не редактируется", 409)
    before = _snapshot(event)
    changed = await _apply_fields(session, user, event, body)
    fresh: set[int] = set()
    if body.sessions is not None:
        sessions_changed, fresh = await _apply_sessions(session, event, body.sessions)
        if sessions_changed:
            changed.add("sessions")
    if not changed:
        return event

    # Правки организатора защищают поля импортированного события от перезаписи (FR-PUB-6).
    imported = await session.scalar(
        select(EventSource.id).where(EventSource.event_id == event.id).limit(1)
    )
    if imported is not None:
        event.locked_fields = sorted(set(event.locked_fields or []) | changed)

    status_before = event.status
    rerun = event.status in _ACTIVE and bool(changed & _MODERATED_FIELDS)
    rejected = False
    if event.status in _ACTIVE:
        sessions = await _sessions(session, event.id)
        if not await _moderate(session, user, event, sessions, fresh, notifier):
            rejected = True
        else:
            event.content_hash = content_hash(event, sessions)
            if rerun and event.trust_tier == TrustTier.community:
                event.status = EventStatus.pending
    diff = audit.changes(before, _snapshot(event))
    if "sessions" in changed:
        diff["sessions"] = "changed"
    if status_before != event.status:
        diff["status"] = [status_before, event.status]
    await audit.record(
        session,
        action="event.update",
        entity_type="event",
        entity_id=event.id,
        actor_user_id=user.id,
        diff=diff,
    )
    if rejected:
        await _after_rules_rejected(session, notifier, event)
        return event
    await session.commit()
    if rerun:
        await jobs.enqueue(MODERATE_EVENT, event.id, 0)
    return event


async def submit(
    session: AsyncSession,
    user: User,
    event_id: int,
    *,
    jobs: JobQueue,
    notifier: Notifier,
) -> Event:
    event = await _require_manage(session, user, event_id, lock=True)
    if event.status not in (EventStatus.draft, EventStatus.rejected):
        raise AppError("bad_transition", "Событие уже отправлено", status_code=409)
    if not await users_service.has_required_consents(session, user):
        raise AppError(
            "consent_required", "Чтобы публиковать события, прими условия и политику", 403
        )
    status_before = event.status
    # Уровень доверия пересчитывается: организацию могли проверить или отозвать.
    event.trust_tier = await _tier_for(session, user, event.organization_id)
    sessions = await _sessions(session, event.id)
    if not await _moderate(session, user, event, sessions, None, notifier):
        await audit.record(
            session,
            action="event.submit",
            entity_type="event",
            entity_id=event.id,
            actor_user_id=user.id,
            diff={"status": [status_before, event.status], "trust_tier": event.trust_tier},
        )
        await _after_rules_rejected(session, notifier, event)
        return event
    digest = content_hash(event, sessions)
    await _check_limits(session, user, event, digest)
    event.content_hash = digest
    event.moderation_reason = None
    if event.trust_tier == TrustTier.official:
        event.status = EventStatus.published
        event.published_at = event.published_at or utcnow()
    else:
        event.status = EventStatus.pending
    await audit.record(
        session,
        action="event.submit",
        entity_type="event",
        entity_id=event.id,
        actor_user_id=user.id,
        diff={"status": [status_before, event.status], "trust_tier": event.trust_tier},
    )
    await session.commit()
    await jobs.enqueue(MODERATE_EVENT, event.id, 0)
    if event.status == EventStatus.pending:
        await notifier.send(
            user.id, texts.EVENT_PENDING_REVIEW.format(title=event.title), f"ev_{event.id}"
        )
    return event


async def cancel(session: AsyncSession, user: User, event_id: int) -> Event:
    event = await _require_manage(session, user, event_id, lock=True)
    if event.status not in (EventStatus.published, EventStatus.pending, EventStatus.hidden):
        raise AppError("bad_transition", "Отменить можно только отправленное событие", 409)
    before = event.status
    event.status = EventStatus.cancelled
    await audit.record(
        session,
        action="event.cancel",
        entity_type="event",
        entity_id=event.id,
        actor_user_id=user.id,
        diff={"status": [before, EventStatus.cancelled]},
    )
    saved_users = await session.scalars(
        select(User)
        .join(SavedSession, SavedSession.user_id == User.id)
        .join(EventSession, EventSession.id == SavedSession.session_id)
        .where(EventSession.event_id == event.id, User.bot_started_at.is_not(None))
    )
    for recipient in saved_users:
        await notifications_service.schedule(
            session,
            recipient,
            kind="cancelled",
            payload={"event_id": event.id, "title": event.title},
            dedup_key=f"cancelled:{recipient.id}:{event.id}",
            scheduled_at=utcnow(),
        )
    await session.commit()
    return event


async def remove(session: AsyncSession, user: User, event_id: int) -> None:
    event = await _require_manage(session, user, event_id, lock=True)
    if event.status != EventStatus.draft:
        raise AppError("bad_transition", "Удалить можно только черновик — иначе отмени", 409)
    await audit.record(
        session,
        action="event.delete",
        entity_type="event",
        entity_id=event.id,
        actor_user_id=user.id,
        diff={"title": event.title},
    )
    await session.execute(delete(Event).where(Event.id == event.id))
    await session.commit()


# --- Представления --------------------------------------------------------------------


async def manage_view(session: AsyncSession, user: User, event_id: int) -> EventManage:
    event = await _require_manage(session, user, event_id)
    org = (
        await session.get(Organization, event.organization_id)
        if event.organization_id is not None
        else None
    )
    venue_out = await venues_service.get_out(session, event.venue_id) if event.venue_id else None
    locality_id = event.locality_id or (venue_out.locality_id if venue_out else None)
    locality = await session.get(Locality, locality_id) if locality_id else None
    sessions = await _sessions(session, event.id)
    return EventManage(
        id=event.id,
        status=event.status,
        trust_tier=event.trust_tier,
        organization_id=event.organization_id,
        org_name=org.name if org else None,
        org_verified=bool(org and orgs_service.is_verified(org)),
        author_user_id=event.author_user_id,
        title=event.title,
        description=event.description,
        short_description=event.short_description,
        category=event.category,
        tags=list(event.tags or []),
        cover_media_id=event.cover_media_id,
        cover_url=event.cover_url,
        venue=(
            VenueBrief(
                id=venue_out.id,
                name=venue_out.name,
                address=venue_out.address,
                lat=venue_out.lat,
                lon=venue_out.lon,
            )
            if venue_out
            else None
        ),
        locality_id=event.locality_id,
        locality_name=locality.name if locality else None,
        timezone=locality.timezone if locality else DEFAULT_TIMEZONE,
        is_online=event.is_online,
        online_url=event.online_url,
        indoor=event.indoor,
        price_type=event.price_type,
        price_min=event.price_min,
        price_max=event.price_max,
        pushkin_card=event.pushkin_card,
        age_rating=event.age_rating,
        registration_required=event.registration_required,
        ticket_url=event.ticket_url,
        contacts=event.contacts,
        accessibility=event.accessibility,
        sessions=[
            SessionOut(id=s.id, starts_at=s.starts_at, ends_at=s.ends_at, status=s.status)
            for s in sessions
        ],
        locked_fields=list(event.locked_fields or []),
        ai_fields=list(event.ai_fields or []),
        moderation_reason=event.moderation_reason,
        published_at=event.published_at,
        created_at=event.created_at,
        updated_at=event.updated_at,
        can_pushkin=await _tier_for(session, user, event.organization_id) == TrustTier.official,
    )


async def _list(session: AsyncSession, condition: Any, status: str | None) -> list[MyEventItem]:
    now = utcnow()
    next_start = (
        select(func.min(EventSession.starts_at))
        .where(
            EventSession.event_id == Event.id,
            EventSession.status == SessionStatus.scheduled,
            func.coalesce(EventSession.ends_at, EventSession.starts_at) >= now,
        )
        .scalar_subquery()
    )
    stmt = (
        select(Event, Organization.name, Locality.timezone, next_start)
        .outerjoin(Organization, Organization.id == Event.organization_id)
        .outerjoin(Venue, Venue.id == Event.venue_id)
        .outerjoin(Locality, Locality.id == func.coalesce(Event.locality_id, Venue.locality_id))
        .where(condition)
        .order_by(Event.updated_at.desc(), Event.id.desc())
        .limit(LIST_LIMIT)
    )
    if status is not None:
        stmt = stmt.where(Event.status == status)
    rows = await session.execute(stmt)
    return [
        MyEventItem(
            id=event.id,
            title=event.title,
            status=event.status,
            trust_tier=event.trust_tier,
            category=event.category,
            cover_url=event.cover_url,
            organization_id=event.organization_id,
            org_name=org_name,
            next_starts_at=starts,
            timezone=timezone or DEFAULT_TIMEZONE,
            moderation_reason=event.moderation_reason,
            updated_at=event.updated_at,
        )
        for event, org_name, timezone, starts in rows.tuples()
    ]


async def my_events(session: AsyncSession, user: User, status: str | None) -> list[MyEventItem]:
    return await _list(session, Event.author_user_id == user.id, status)


async def org_events(
    session: AsyncSession, user: User, org_id: int, status: str | None
) -> list[MyEventItem]:
    await orgs_service.require_member(session, org_id, user)
    return await _list(session, Event.organization_id == org_id, status)
