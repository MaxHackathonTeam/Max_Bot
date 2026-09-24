"""Создание тестовых сущностей напрямую в БД.

Тесты делят одну базу, поэтому каждый берёт свою «область» координат (`random_area`)
и фильтрует ленту по ней — так соседние тесты не видят чужих событий.
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventStatus, LocalityKind, OrgKind, TrustTier, VerificationStatus
from app.models.events import Event, EventSession
from app.models.geo import Locality, Venue
from app.models.orgs import Organization
from app.models.users import User
from app.services.localities import wkt_point

KM_PER_DEG_LAT = 111.0


def random_area() -> tuple[float, float]:
    """Точка в малонаселённой зоне; области разных тестов почти не пересекаются в 50 км."""
    return random.uniform(62.0, 70.0), random.uniform(95.0, 160.0)


def shift_north(lat: float, lon: float, km: float) -> tuple[float, float]:
    return lat + km / KM_PER_DEG_LAT, lon


def in_hours(hours: float) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


async def make_locality(
    session: AsyncSession,
    name: str,
    lat: float,
    lon: float,
    *,
    kind: str = LocalityKind.village,
    timezone: str = "Europe/Moscow",
) -> Locality:
    locality = Locality(
        name=name,
        kind=kind,
        region="Тестовая область",
        point=wkt_point(lat, lon),
        timezone=timezone,
        source="test",
    )
    session.add(locality)
    await session.flush()
    return locality


async def make_venue(
    session: AsyncSession, locality: Locality, lat: float, lon: float, name: str = "ДК"
) -> Venue:
    venue = Venue(
        name=name,
        address=f"{locality.name}, ул. Центральная, 1",
        locality_id=locality.id,
        point=wkt_point(lat, lon),
        source="test",
    )
    session.add(venue)
    await session.flush()
    return venue


async def make_org(session: AsyncSession, *, verified: bool = True) -> Organization:
    creator = User(first_name="Организатор")
    session.add(creator)
    await session.flush()
    org = Organization(
        name="Дом культуры",
        kind=OrgKind.dk,
        created_by=creator.id,
        verification_status=(
            VerificationStatus.verified if verified else VerificationStatus.unverified
        ),
    )
    session.add(org)
    await session.flush()
    return org


async def make_event(
    session: AsyncSession,
    locality: Locality,
    *,
    title: str = "Событие",
    starts: list[datetime] | None = None,
    venue: Venue | None = None,
    trust_tier: str = TrustTier.official,
    org: Organization | None = None,
    status: str = EventStatus.published,
    category: str = "concert",
    price_type: str = "free",
    **fields: Any,
) -> Event:
    event = Event(
        title=title,
        trust_tier=trust_tier,
        status=status,
        locality_id=locality.id,
        venue_id=venue.id if venue else None,
        organization_id=org.id if org else None,
        category=category,
        price_type=price_type,
        **fields,
    )
    session.add(event)
    await session.flush()
    for starts_at in starts if starts is not None else [in_hours(3)]:
        session.add(EventSession(event_id=event.id, starts_at=starts_at))
    await session.flush()
    return event
