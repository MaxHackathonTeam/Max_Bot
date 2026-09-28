"""Площадки: свои площадки организации и поиск по названию (FR-PUB-1, шаг «Где»)."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.geo import Locality, Venue
from app.models.users import User
from app.schemas.venues import VenueIn, VenueOut
from app.services import audit
from app.services import localities as localities_service
from app.services import orgs as orgs_service
from app.services.localities import lat_of, lon_of, wkt_point

SEARCH_LIMIT = 20


def _out(venue: Venue, locality_name: str | None, lat: float, lon: float) -> VenueOut:
    return VenueOut(
        id=venue.id,
        name=venue.name,
        address=venue.address,
        locality_id=venue.locality_id,
        locality_name=locality_name,
        lat=lat,
        lon=lon,
        org_id=venue.org_id,
    )


async def get_out(session: AsyncSession, venue_id: int) -> VenueOut | None:
    row = (
        await session.execute(
            select(Venue, Locality.name, lat_of(Venue.point), lon_of(Venue.point))
            .join(Locality, Locality.id == Venue.locality_id)
            .where(Venue.id == venue_id)
        )
    ).first()
    return _out(*row) if row is not None else None


async def search(
    session: AsyncSession, user: User, q: str | None, org_id: int | None
) -> list[VenueOut]:
    """Площадки организации (для участника) и найденные по названию или адресу.

    Поиск не показывает площадки чужих организаций: выбрать их всё равно нельзя
    (event_editor._check_refs), а в подсказке они только мешают.
    """
    stmt = (
        select(Venue, Locality.name, lat_of(Venue.point), lon_of(Venue.point))
        .join(Locality, Locality.id == Venue.locality_id)
        .limit(SEARCH_LIMIT)
    )
    mine = [org.id for org, _ in await orgs_service.list_mine(session, user)]
    conditions = []
    if org_id is not None:
        await orgs_service.require_member(session, org_id, user)
        conditions.append(Venue.org_id == org_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(Venue.name.ilike(pattern), Venue.address.ilike(pattern))
            & or_(Venue.org_id.is_(None), Venue.org_id.in_(mine))
        )
    if not conditions:
        # Без запроса — только площадки, созданные в организациях пользователя.
        if not mine:
            return []
        conditions.append(Venue.org_id.in_(mine))
    stmt = stmt.where(or_(*conditions)).order_by(Venue.org_id.is_(None), Venue.name, Venue.id)
    return [_out(*row) for row in (await session.execute(stmt)).all()]


async def create(session: AsyncSession, user: User, body: VenueIn) -> VenueOut:
    if body.org_id is not None:
        await orgs_service.require_member(session, body.org_id, user)
    locality_id = body.locality_id
    lat, lon = body.lat, body.lon
    if locality_id is not None:
        locality = await localities_service.get_out(session, locality_id)
        if locality is None:
            raise AppError("locality_not_found", "Населённый пункт не найден", status_code=422)
        if lat is None or lon is None:
            # Без координат — центр населённого пункта.
            lat, lon = locality.lat, locality.lon
    elif lat is not None and lon is not None:
        nearest = await localities_service.nearest(session, lat, lon, limit=1)
        if not nearest:
            raise AppError(
                "locality_not_found",
                "Не нашёл населённый пункт рядом с этой точкой — выбери его вручную",
                status_code=422,
            )
        locality_id = nearest[0].id
    else:
        raise AppError(
            "locality_required",
            "Укажи населённый пункт или точку на карте",
            status_code=422,
        )
    venue = Venue(
        name=body.name.strip(),
        address=body.address,
        locality_id=locality_id,
        point=wkt_point(lat, lon),
        fias_id=body.fias_id,
        org_id=body.org_id,
        source="user",
    )
    session.add(venue)
    await session.flush()
    await audit.record(
        session,
        action="venue.create",
        entity_type="venue",
        entity_id=venue.id,
        actor_user_id=user.id,
        diff={"name": venue.name, "org_id": venue.org_id, "locality_id": locality_id},
    )
    await session.commit()
    out = await get_out(session, venue.id)
    assert out is not None  # noqa: S101 — только что создана
    return out
