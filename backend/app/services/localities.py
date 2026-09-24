"""Справочник населённых пунктов (§7.5): поиск, ближайший, ленивое пополнение из геокодера."""

from functools import lru_cache
from typing import Any

import structlog
from geoalchemy2 import Geography, Geometry, WKTElement
from sqlalchemy import ColumnElement, Select, cast, desc, func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from timezonefinder import TimezoneFinder

from app.integrations.geo import GeoAddress, GeoPlace, GeoProvider
from app.models.enums import AuditActor, LocalityKind
from app.models.geo import Locality
from app.schemas.geo import AddressOut, LocalityOut
from app.services import audit

log = structlog.get_logger(__name__)

DEFAULT_TIMEZONE = "Europe/Moscow"
# Геокодер не спрашиваем, если в справочнике уже нашлось столько вариантов.
ENOUGH_LOCAL_RESULTS = 3
# Точка ближе этого расстояния к НП из справочника — считаем, что пользователь в нём.
NEAR_ENOUGH_M = 3_000
NEAREST_MAX_M = 50_000
SAME_PLACE_M = 5_000


@lru_cache
def _tz_finder() -> TimezoneFinder:
    return TimezoneFinder()


def timezone_for(lat: float, lon: float) -> str:
    return _tz_finder().timezone_at(lng=lon, lat=lat) or DEFAULT_TIMEZONE


def geo_point(lat: float, lon: float) -> ColumnElement[Any]:
    return cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography)


def wkt_point(lat: float, lon: float) -> Any:
    return WKTElement(f"POINT({lon} {lat})", srid=4326)


def lat_of(column: Any) -> ColumnElement[float]:
    return func.ST_Y(cast(column, Geometry))


def lon_of(column: Any) -> ColumnElement[float]:
    return func.ST_X(cast(column, Geometry))


def _select_out(origin: ColumnElement[Any] | None = None) -> Select[Any]:
    columns: list[Any] = [
        Locality,
        lat_of(Locality.point).label("lat"),
        lon_of(Locality.point).label("lon"),
    ]
    if origin is not None:
        columns.append((func.ST_Distance(Locality.point, origin) / 1000).label("distance_km"))
    return select(*columns)


def _to_out(row: Any) -> LocalityOut:
    locality: Locality = row[0]
    distance = row[3] if len(row) > 3 else None
    return LocalityOut(
        id=locality.id,
        name=locality.name,
        kind=locality.kind,
        region=locality.region,
        municipality=locality.municipality,
        lat=row[1],
        lon=row[2],
        timezone=locality.timezone,
        distance_km=round(distance, 1) if distance is not None else None,
    )


async def get_out(session: AsyncSession, locality_id: int) -> LocalityOut | None:
    row = (await session.execute(_select_out().where(Locality.id == locality_id))).first()
    return _to_out(row) if row is not None else None


async def _search_db(session: AsyncSession, query: str, limit: int) -> list[LocalityOut]:
    prefix = Locality.name.istartswith(query, autoescape=True)
    stmt = (
        _select_out()
        .where(prefix | Locality.name.op("%")(query))
        .order_by(
            desc(func.lower(Locality.name) == query.lower()),
            desc(prefix),
            desc(func.similarity(Locality.name, query)),
            nulls_last(desc(Locality.population)),
            Locality.id,
        )
        .limit(limit)
    )
    return [_to_out(row) for row in (await session.execute(stmt)).all()]


async def upsert_place(session: AsyncSession, place: GeoPlace) -> Locality:
    """Находит НП в справочнике (по ФИАС или по имени рядом с точкой) или создаёт его."""
    existing = None
    if place.fias_id:
        existing = await session.scalar(select(Locality).where(Locality.fias_id == place.fias_id))
    if existing is None:
        existing = await session.scalar(
            select(Locality)
            .where(
                func.lower(Locality.name) == place.name.lower(),
                func.ST_DWithin(Locality.point, geo_point(place.lat, place.lon), SAME_PLACE_M),
            )
            .limit(1)
        )
    if existing is not None:
        return existing
    kind = place.kind if place.kind in LocalityKind.__members__ else LocalityKind.other
    locality = Locality(
        fias_id=place.fias_id,
        name=place.name[:255],
        kind=kind,
        region=place.region,
        region_code=place.region_code,
        municipality=place.municipality,
        point=wkt_point(place.lat, place.lon),
        timezone=timezone_for(place.lat, place.lon),
        source=place.source or "geocoder",
    )
    session.add(locality)
    await session.flush()
    await audit.record(
        session,
        action="locality.create",
        entity_type="locality",
        entity_id=locality.id,
        actor_type=AuditActor.system,
        diff={"name": locality.name, "source": locality.source, "region": locality.region},
    )
    return locality


async def search(
    session: AsyncSession, query: str, geo: GeoProvider | None, limit: int = 10
) -> list[LocalityOut]:
    query = query.strip()
    if len(query) < 2:
        return []
    found = await _search_db(session, query, limit)
    if len(found) >= ENOUGH_LOCAL_RESULTS or geo is None:
        return found
    try:
        places = await geo.suggest_localities(query, 5)
    except Exception as exc:
        # Геокодер — только дополнение: без него работаем по справочнику.
        log.warning("geo_suggest_failed", error=type(exc).__name__)
        return found
    if not places:
        return found
    for place in places:
        await upsert_place(session, place)
    await session.commit()
    return await _search_db(session, query, limit)


async def _nearest_db(
    session: AsyncSession, lat: float, lon: float, max_m: int, limit: int
) -> list[LocalityOut]:
    origin = geo_point(lat, lon)
    stmt = (
        _select_out(origin)
        .where(func.ST_DWithin(Locality.point, origin, max_m))
        .order_by(func.ST_Distance(Locality.point, origin), Locality.id)
        .limit(limit)
    )
    return [_to_out(row) for row in (await session.execute(stmt)).all()]


async def nearest(
    session: AsyncSession, lat: float, lon: float, geo: GeoProvider | None, limit: int = 5
) -> list[LocalityOut]:
    """Ближайшие НП; если рядом со справочными нет — спрашиваем геокодер и добавляем."""
    close = await _nearest_db(session, lat, lon, NEAR_ENOUGH_M, 1)
    if not close and geo is not None:
        try:
            place = await geo.reverse_locality(lat, lon)
        except Exception as exc:
            log.warning("geo_reverse_failed", error=type(exc).__name__)
            place = None
        if place is not None:
            await upsert_place(session, place)
            await session.commit()
    return await _nearest_db(session, lat, lon, NEAREST_MAX_M, limit)


def _address_out(address: GeoAddress) -> AddressOut:
    return AddressOut(
        value=address.value,
        lat=address.lat,
        lon=address.lon,
        fias_id=address.fias_id,
        locality_name=address.locality.name if address.locality else None,
    )


async def suggest_addresses(
    geo: GeoProvider | None, query: str, limit: int = 5
) -> list[AddressOut]:
    query = query.strip()
    if geo is None or len(query) < 3:
        return []
    try:
        addresses = await geo.suggest_addresses(query, limit)
    except Exception as exc:
        log.warning("geo_address_suggest_failed", error=type(exc).__name__)
        return []
    return [_address_out(a) for a in addresses]
