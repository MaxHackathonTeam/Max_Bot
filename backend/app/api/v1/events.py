"""Лента, карточка события и «Пойду» (FR-CAT, FR-EV, FR-NTF-1)."""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import AuthDep, JobsDep, NotifierDep, OptionalAuthDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.schemas.events import EventDetail, EventPage, SaveIn, SaveOut
from app.schemas.manage import (
    CheckOut,
    EventCreate,
    EventManage,
    EventPatch,
    ReportIn,
    ReportOut,
)
from app.services import analytics, event_editor
from app.services import events as events_service
from app.services import moderation as moderation_service
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
    time_from: Annotated[
        int | None, Query(ge=0, le=23, description="Начало не раньше этого часа, местное время")
    ] = None,
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
        time_from=time_from,
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
    detail = await events_service.get_detail(
        session,
        event_id,
        origin=origin,
        saved_session_ids=saved_ids,
        bot_username=settings.max_bot_username,
    )
    await analytics.record(
        session, "event_view", user_id=auth.user.id if auth else None, props={"event_id": event_id}
    )
    await session.commit()
    return detail


@router.post("/{event_id}/share-card", summary="Подготовить карточку для shareMaxContent")
async def share_card(
    event_id: int, auth: AuthDep, session: SessionDep, request: Request
) -> dict[str, Any]:
    event = await events_service.get_detail(session, event_id)
    client = getattr(request.app.state, "max_client", None)
    if client is None or auth.user.dialog_chat_id is None:
        raise AppError("bot_unavailable", "Карточка для шеринга пока недоступна", 503)
    result = await client.send_message(
        chat_id=auth.user.dialog_chat_id, text=f"{event.title}\n{event.share_url or ''}"
    )
    body = result.get("message", result) if isinstance(result, dict) else {}
    mid = body.get("mid") if isinstance(body, dict) else None
    if not mid:
        raise AppError("share_failed", "Не удалось подготовить карточку", 502)
    await analytics.record(
        session, "event_share", user_id=auth.user.id, props={"event_id": event_id}
    )
    await session.commit()
    return {"mid": str(mid), "chat_type": "DIALOG"}


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


# --- Управление событием (FR-PUB) ------------------------------------------------------


@router.post("", response_model=EventManage, status_code=201, summary="Создать черновик")
async def create_event(body: EventCreate, auth: AuthDep, session: SessionDep) -> EventManage:
    event = await event_editor.create(session, auth.user, body)
    return await event_editor.manage_view(session, auth.user, event.id)


@router.get("/{event_id}/manage", response_model=EventManage, summary="Событие для редактирования")
async def manage_event(event_id: int, auth: AuthDep, session: SessionDep) -> EventManage:
    return await event_editor.manage_view(session, auth.user, event_id)


@router.patch("/{event_id}", response_model=EventManage, summary="Изменить событие")
async def patch_event(
    event_id: int,
    body: EventPatch,
    auth: AuthDep,
    session: SessionDep,
    jobs: JobsDep,
    notifier: NotifierDep,
) -> EventManage:
    await event_editor.patch(session, auth.user, event_id, body, jobs=jobs, notifier=notifier)
    return await event_editor.manage_view(session, auth.user, event_id)


@router.post("/{event_id}/submit", response_model=EventManage, summary="Отправить на публикацию")
async def submit_event(
    event_id: int, auth: AuthDep, session: SessionDep, jobs: JobsDep, notifier: NotifierDep
) -> EventManage:
    await event_editor.submit(session, auth.user, event_id, jobs=jobs, notifier=notifier)
    return await event_editor.manage_view(session, auth.user, event_id)


@router.post("/{event_id}/check", response_model=CheckOut, summary="Проверить перед отправкой")
async def check_event(event_id: int, auth: AuthDep, session: SessionDep) -> CheckOut:
    return await event_editor.precheck(session, auth.user, event_id)


@router.post("/{event_id}/cancel", response_model=EventManage, summary="Отменить событие")
async def cancel_event(event_id: int, auth: AuthDep, session: SessionDep) -> EventManage:
    await event_editor.cancel(session, auth.user, event_id)
    return await event_editor.manage_view(session, auth.user, event_id)


@router.delete("/{event_id}", status_code=204, summary="Удалить черновик")
async def delete_event(event_id: int, auth: AuthDep, session: SessionDep) -> Response:
    await event_editor.remove(session, auth.user, event_id)
    return Response(status_code=204)


@router.post("/{event_id}/report", response_model=ReportOut, summary="Пожаловаться")
async def report_event(
    event_id: int, body: ReportIn, auth: AuthDep, session: SessionDep, notifier: NotifierDep
) -> ReportOut:
    accepted = await moderation_service.report(session, auth.user, event_id, body, notifier)
    return ReportOut(accepted=accepted)
