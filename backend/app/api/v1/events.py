"""Лента, карточка события и «Пойду» (FR-CAT, FR-EV, FR-NTF-1)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AuthDep, OptionalAuthDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.schemas.events import EventDetail, EventPage, SaveIn, SaveOut
from app.services import events as events_service
from app.services import saved as saved_service
from app.services.events import EventFilters, Origin
from app.services.localities import timezone_for

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=EventPage, summary="Лента событий")
async def list_events(
    session: SessionDep,
    auth: OptionalAuthDep,
    locality_id: int | None = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[int, Query(description="5, 15, 30 или 50")] = 30,
    date_preset: Annotated[
        Literal["today", "tomorrow", "weekend"] | None, Query(alias="date")
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    category: Annotated[list[str] | None, Query(description="Можно несколько")] = None,
    free: bool = False,
    price_max: Annotated[int | None, Query(ge=0)] = None,
    pushkin: bool = False,
    age: Annotated[int | None, Query(ge=0, le=120)] = None,
    tier: Literal["official", "community", "all"] = "official",
    format: Literal["all", "offline", "online"] = "all",
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["date", "distance", "relevance"] | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=events_service.MAX_LIMIT)] = events_service.DEFAULT_LIMIT,
    include_total: bool = False,
) -> EventPage:
    if radius_km not in events_service.RADIUS_CHOICES:
        raise AppError("bad_request", "Радиус может быть 5, 15, 30 или 50 км")
    if (lat is None) != (lon is None):
        raise AppError("bad_request", "Нужны обе координаты: lat и lon")
    if date_from and date_to and date_from > date_to:
        raise AppError("bad_request", "Начало периода позже конца")
    if age is None and auth is not None and auth.user.birth_year:
        age = date.today().year - auth.user.birth_year
    filters = EventFilters(
        locality_id=locality_id,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        date_preset=date_preset,
        date_from=date_from,
        date_to=date_to,
        categories=category or [],
        free=free,
        price_max=price_max,
        pushkin=pushkin,
        age=age,
        tier=tier,
        format=format,
        q=q,
        sort=sort,
        cursor=cursor,
        limit=limit,
        include_total=include_total,
    )
    return await events_service.search(session, filters)


@router.get("/{event_id}", response_model=EventDetail, summary="Карточка события")
async def get_event(
    event_id: int,
    session: SessionDep,
    auth: OptionalAuthDep,
    settings: SettingsDep,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> EventDetail:
    origin = None
    if lat is not None and lon is not None:
        origin = Origin(lat, lon, timezone_for(lat, lon))
    elif auth is not None and auth.user.locality_id is not None:
        origin = await events_service.resolve_origin(
            session, EventFilters(locality_id=auth.user.locality_id)
        )
    saved_ids: list[int] = []
    if auth is not None:
        saved_ids = await saved_service.saved_session_ids(session, auth.user.id, event_id)
    return await events_service.get_detail(
        session,
        event_id,
        origin=origin,
        saved_session_ids=saved_ids,
        bot_username=settings.max_bot_username,
    )


@router.post("/{event_id}/save", response_model=SaveOut, summary="«Пойду» на сеанс")
async def save_event(
    event_id: int, auth: AuthDep, session: SessionDep, body: SaveIn | None = None
) -> SaveOut:
    session_id = body.session_id if body is not None else None
    ids = await saved_service.save(session, auth.user, event_id, session_id)
    return SaveOut(saved_session_ids=ids)


@router.delete("/{event_id}/save", response_model=SaveOut, summary="Убрать «Пойду»")
async def unsave_event(
    event_id: int, auth: AuthDep, session: SessionDep, session_id: int | None = None
) -> SaveOut:
    ids = await saved_service.unsave(session, auth.user, event_id, session_id)
    return SaveOut(saved_session_ids=ids)
