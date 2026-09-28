"""Справочник населённых пунктов (§7.5): поиск (pg_trgm) и ближайший (PostGIS) по локальной БД."""

from functools import lru_cache
from typing import Any

from geoalchemy2 import Geography, Geometry, WKTElement
from sqlalchemy import ColumnElement, Select, cast, desc, func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from timezonefinder import TimezoneFinder

from app.models.geo import Locality
from app.schemas.geo import LocalityOut

DEFAULT_TIMEZONE = "Europe/Moscow"
NEAREST_MAX_M = 50_000
SAME_PLACE_M = 5_000
# Привязка демо-НП к справочнику: координаты демо-набора бывают неточны на 10–20 км,
# а в OSM имя бывает длиннее («Ростов» → «Ростов Великий»).
SAME_NAME_M = 25_000


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


_NORM_TABLE = str.maketrans({"ё": "е", "-": " ", "–": " "})


def normalize(text: str) -> str:
    """Как колонка name_norm: lower, ё→е, дефисы → пробел (плюс схлопываем пробелы)."""
    return " ".join(text.lower().translate(_NORM_TABLE).split())


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _search_db(session: AsyncSession, query: str, limit: int) -> list[LocalityOut]:
    # Порядок: точное совпадение > префикс > похожесть (pg_trgm) > население.
    # Тёзки различаются районом и регионом в ответе.
    norm = normalize(query)
    prefix = Locality.name_norm.like(_escape_like(norm) + "%", escape="\\")
    stmt = (
        _select_out()
        .where(prefix | Locality.name_norm.op("%")(norm))
        .order_by(
            desc(Locality.name_norm == norm),
            desc(prefix),
            desc(func.similarity(Locality.name_norm, norm)),
            nulls_last(desc(Locality.population)),
            Locality.id,
        )
        .limit(limit)
    )
    return [_to_out(row) for row in (await session.execute(stmt)).all()]


async def search(session: AsyncSession, query: str, limit: int = 10) -> list[LocalityOut]:
    query = query.strip()
    if len(query) < 2:
        return []
    return await _search_db(session, query, min(limit, 10))


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
    session: AsyncSession, lat: float, lon: float, limit: int = 5
) -> list[LocalityOut]:
    """Ближайшие НП из справочника в радиусе NEAREST_MAX_M."""
    return await _nearest_db(session, lat, lon, NEAREST_MAX_M, limit)
