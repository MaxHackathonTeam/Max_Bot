"""Открытый профиль организации и поиск организаций — без токена, для всех.

Отдаём только публичное: название, «О нас», вид, пункт, адрес, сайт, ВК и статус проверки.
ИНН/ОГРН (ИНН ИП — персональные данные, §11), телефон, почта и состав команды сюда не
попадают. Организации с отозванной проверкой скрыты: профиль — 404, в поиске их нет.
Афиши — те же, что в ленте: только опубликованные с будущими сеансами, ленты
«Официальные» и «От жителей» отдаются раздельно.
"""

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.demo.orgs import SEED_USERNAME
from app.models.enums import EventStatus, OrgKind, SessionStatus, VerificationStatus
from app.models.events import Event, EventSession
from app.models.geo import Locality
from app.models.orgs import Organization
from app.models.users import User
from app.schemas.events import EventPage, LocalityBrief
from app.schemas.orgs import OrgPublic, OrgSearchItem, OrgSearchPage
from app.services import events as events_service

DEFAULT_LIMIT = 20
MAX_LIMIT = 50
MAX_QUERY = 100
# Как в ленте: одна опечатка в коротком слове должна проходить.
TYPO_THRESHOLD = events_service.TYPO_THRESHOLD


@dataclass(frozen=True)
class FutureCounts:
    total: int = 0
    official: int = 0
    community: int = 0


def _not_found() -> AppError:
    return AppError("org_not_found", "Организация не найдена", status_code=404)


def visible() -> ColumnElement[bool]:
    return Organization.verification_status != VerificationStatus.revoked


def is_demo() -> ColumnElement[bool]:
    """Демо-организации созданы служебным пользователем загрузчика (`make seed`)."""
    seed_user = select(User.id).where(User.username == SEED_USERNAME, User.max_user_id.is_(None))
    return Organization.created_by.in_(seed_user.scalar_subquery())


def _base() -> Select[Any]:
    return (
        select(Organization, Locality.id, Locality.name, is_demo().label("is_demo"))
        .outerjoin(Locality, Locality.id == Organization.locality_id)
        .where(visible())
    )


def _locality(locality_id: int | None, name: str | None) -> LocalityBrief | None:
    if locality_id is None or name is None:
        return None
    return LocalityBrief(id=locality_id, name=name)


async def future_counts(
    session: AsyncSession, org_ids: Sequence[int], now: datetime | None = None
) -> dict[int, FutureCounts]:
    """Сколько у организаций опубликованных событий с будущими сеансами — по лентам."""
    if not org_ids:
        return {}
    now = now or events_service.utcnow()
    upcoming = exists(
        select(EventSession.id).where(
            EventSession.event_id == Event.id,
            EventSession.status == SessionStatus.scheduled,
            func.coalesce(EventSession.ends_at, EventSession.starts_at) >= now,
        )
    )
    rows = await session.execute(
        select(
            Event.organization_id,
            func.count(),
            func.count().filter(events_service.tier_condition("official")),
            func.count().filter(events_service.tier_condition("community")),
        )
        .where(
            Event.organization_id.in_(org_ids),
            Event.status == EventStatus.published,
            upcoming,
        )
        .group_by(Event.organization_id)
    )
    return {
        org_id: FutureCounts(total, official, community)
        for org_id, total, official, community in rows.tuples()
        if org_id is not None
    }


async def get_public(session: AsyncSession, org_id: int) -> OrgPublic:
    row = (await session.execute(_base().where(Organization.id == org_id))).first()
    if row is None:
        raise _not_found()
    org: Organization = row[0]
    counts = (await future_counts(session, [org.id])).get(org.id, FutureCounts())
    return OrgPublic(
        id=org.id,
        name=org.name,
        kind=OrgKind(org.kind),
        description=org.description,
        locality=_locality(row[1], row[2]),
        address=org.address,
        website=org.website,
        vk_url=org.vk_url,
        verified=org.verification_status == VerificationStatus.verified,
        is_demo=bool(row.is_demo),
        future_events=counts.total,
        official_events=counts.official,
        community_events=counts.community,
    )


async def public_events(
    session: AsyncSession,
    org_id: int,
    *,
    tier: events_service.Tier = "official",
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> EventPage:
    """Афиши организации: как в ленте, но без привязки к месту и строго из одной ленты."""
    found = await session.scalar(
        select(Organization.id).where(Organization.id == org_id, visible())
    )
    if found is None:
        raise _not_found()
    filters = events_service.EventFilters(
        organization_id=org_id, tier=tier, sort="date", cursor=cursor, limit=limit
    )
    return await events_service.search(session, filters)


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"o": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        offset = json.loads(raw)["o"]
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError
        return offset
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise AppError(
            "invalid_cursor", "Некорректный курсор, повтори поиск", status_code=400
        ) from exc


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search(
    session: AsyncSession,
    *,
    q: str | None = None,
    locality_id: int | None = None,
    kind: OrgKind | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> OrgSearchPage:
    """Нечёткий поиск по названию (pg_trgm) с фильтрами; без запроса — по алфавиту.

    Вхождение подстроки выше похожести с опечаткой; при равенстве — проверенные выше.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    offset = _decode_cursor(cursor) if cursor else 0
    query = " ".join((q or "").split())[:MAX_QUERY]
    verified = Organization.verification_status == VerificationStatus.verified
    stmt = _base()
    if locality_id is not None:
        stmt = stmt.where(Organization.locality_id == locality_id)
    if kind is not None:
        stmt = stmt.where(Organization.kind == kind)
    if query:
        await session.execute(
            text(f"SET LOCAL pg_trgm.word_similarity_threshold = {TYPO_THRESHOLD}")
        )
        substring = Organization.name.ilike(f"%{_escape_like(query)}%", escape="\\")
        stmt = stmt.where(or_(Organization.name.op("%>")(query), substring)).order_by(
            substring.desc(),
            func.word_similarity(query, Organization.name).desc(),
            verified.desc(),
            Organization.name,
            Organization.id,
        )
    else:
        stmt = stmt.order_by(verified.desc(), Organization.name, Organization.id)
    rows = (await session.execute(stmt.offset(offset).limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    counts = await future_counts(session, [row[0].id for row in rows])
    items = [
        OrgSearchItem(
            id=row[0].id,
            name=row[0].name,
            kind=OrgKind(row[0].kind),
            locality=_locality(row[1], row[2]),
            verified=row[0].verification_status == VerificationStatus.verified,
            is_demo=bool(row.is_demo),
            future_events=counts.get(row[0].id, FutureCounts()).total,
        )
        for row in rows
    ]
    return OrgSearchPage(
        items=items, next_cursor=_encode_cursor(offset + limit) if has_more else None
    )
