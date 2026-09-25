"""«Пойду» — сохранение сеансов (FR-NTF-1). Напоминания по ним — этап 4."""

from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import EventStatus, SessionStatus
from app.models.events import Event, EventSession, SavedSession
from app.models.users import User
from app.schemas.events import SavedItem, SessionOut
from app.services import audit
from app.services import events as events_service
from app.services import users as users_service

SAVED_LIST_LIMIT = 100


async def saved_session_ids(session: AsyncSession, user_id: int, event_id: int) -> list[int]:
    rows = await session.scalars(
        select(SavedSession.session_id)
        .join(EventSession, EventSession.id == SavedSession.session_id)
        .where(SavedSession.user_id == user_id, EventSession.event_id == event_id)
        .order_by(SavedSession.session_id)
    )
    return list(rows)


async def _pick_session(
    session: AsyncSession, event_id: int, session_id: int | None
) -> EventSession:
    now = events_service.utcnow()
    stmt = select(EventSession).where(
        EventSession.event_id == event_id,
        EventSession.status == SessionStatus.scheduled,
        func.coalesce(EventSession.ends_at, EventSession.starts_at) >= now,
    )
    if session_id is not None:
        stmt = stmt.where(EventSession.id == session_id)
    picked = await session.scalar(stmt.order_by(EventSession.starts_at, EventSession.id).limit(1))
    if picked is None:
        if session_id is not None:
            raise AppError(
                "session_unavailable", "Этот сеанс уже прошёл или отменён", status_code=409
            )
        raise AppError("event_past", "У события нет будущих сеансов", status_code=409)
    return picked


async def save(
    session: AsyncSession, user: User, event_id: int, session_id: int | None = None
) -> list[int]:
    """Идемпотентно: повторное «Пойду» на тот же сеанс ничего не меняет."""
    if not await users_service.has_required_consents(session, user):
        raise AppError(
            "consent_required",
            "Чтобы сохранять события, прими условия и политику",
            status_code=403,
        )
    event = await session.get(Event, event_id)
    if event is None or event.status != EventStatus.published:
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    picked = await _pick_session(session, event_id, session_id)
    inserted = await session.scalar(
        insert(SavedSession)
        .values(user_id=user.id, session_id=picked.id)
        .on_conflict_do_nothing(index_elements=["user_id", "session_id"])
        .returning(SavedSession.id)
    )
    if inserted is not None:
        await audit.record(
            session,
            action="event.save",
            entity_type="event",
            entity_id=event_id,
            actor_user_id=user.id,
            diff={"session_id": picked.id},
        )
    await session.commit()
    return await saved_session_ids(session, user.id, event_id)


async def unsave(
    session: AsyncSession, user: User, event_id: int, session_id: int | None = None
) -> list[int]:
    """Без `session_id` снимает «Пойду» со всех сеансов события."""
    event_sessions = select(EventSession.id).where(EventSession.event_id == event_id)
    if session_id is not None:
        event_sessions = event_sessions.where(EventSession.id == session_id)
    removed = list(
        await session.scalars(
            delete(SavedSession)
            .where(
                SavedSession.user_id == user.id,
                SavedSession.session_id.in_(event_sessions.scalar_subquery()),
            )
            .returning(SavedSession.session_id)
        )
    )
    if removed:
        await audit.record(
            session,
            action="event.unsave",
            entity_type="event",
            entity_id=event_id,
            actor_user_id=user.id,
            diff={"session_ids": sorted(removed)},
        )
    await session.commit()
    return await saved_session_ids(session, user.id, event_id)


async def list_saved(
    session: AsyncSession, user: User, when: Literal["upcoming", "past"] = "upcoming"
) -> list[SavedItem]:
    now = events_service.utcnow()
    session_end = func.coalesce(EventSession.ends_at, EventSession.starts_at)
    stmt = (
        select(EventSession)
        .join(SavedSession, SavedSession.session_id == EventSession.id)
        .join(Event, Event.id == EventSession.event_id)
        .where(
            SavedSession.user_id == user.id,
            Event.status.in_(events_service.PUBLIC_STATUSES),
        )
        .limit(SAVED_LIST_LIMIT)
    )
    if when == "upcoming":
        stmt = stmt.where(session_end >= now).order_by(EventSession.starts_at, EventSession.id)
    else:
        stmt = stmt.where(session_end < now).order_by(
            EventSession.starts_at.desc(), EventSession.id.desc()
        )
    sessions = list(await session.scalars(stmt))
    outs = [
        SessionOut(id=s.id, starts_at=s.starts_at, ends_at=s.ends_at, status=s.status)
        for s in sessions
    ]
    event_ids = list(dict.fromkeys(s.event_id for s in sessions))
    first_by_event: dict[int, SessionOut] = {}
    for s, out in zip(sessions, outs, strict=True):
        first_by_event.setdefault(s.event_id, out)
    cards = await events_service.build_cards(session, event_ids, first_by_event, {}, now)
    card_by_id = {c.id: c for c in cards}
    return [
        SavedItem(session=out, event=card_by_id[s.event_id])
        for s, out in zip(sessions, outs, strict=True)
    ]
