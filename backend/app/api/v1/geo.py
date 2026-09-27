"""Справочники: категории и населённые пункты (§7.5). Доступны без входа."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.core.errors import AppError
from app.schemas.geo import CategoryOut, LocalityOut
from app.services import localities as localities_service
from app.services.categories import CATEGORIES

router = APIRouter(tags=["geo"])


@router.get("/categories", response_model=list[CategoryOut], summary="Категории событий")
async def list_categories() -> list[CategoryOut]:
    return [CategoryOut(slug=c.slug, name=c.name, emoji=c.emoji) for c in CATEGORIES]


@router.get("/localities", response_model=list[LocalityOut], summary="Поиск населённого пункта")
async def search_localities(
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
) -> list[LocalityOut]:
    return await localities_service.search(session, q, limit)


@router.get(
    "/localities/nearest",
    response_model=list[LocalityOut],
    summary="Ближайшие населённые пункты к точке",
)
async def nearest_localities(
    session: SessionDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[LocalityOut]:
    return await localities_service.nearest(session, lat, lon, limit)


@router.get("/localities/{locality_id}", response_model=LocalityOut, summary="Населённый пункт")
async def get_locality(locality_id: int, session: SessionDep) -> LocalityOut:
    locality = await localities_service.get_out(session, locality_id)
    if locality is None:
        raise AppError("not_found", "Населённый пункт не найден", status_code=404)
    return locality
