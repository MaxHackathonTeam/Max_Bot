"""Площадки и загрузка обложек (FR-PUB-1)."""

from typing import Annotated

from fastapi import APIRouter, Query, UploadFile

from app.api.deps import AuthDep, GeoDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.schemas.venues import MediaOut, VenueIn, VenueOut
from app.services import media as media_service
from app.services import venues as venues_service

router = APIRouter(tags=["venues"])


@router.get("/venues", response_model=list[VenueOut], summary="Найти площадку")
async def search_venues(
    auth: AuthDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    org_id: int | None = None,
) -> list[VenueOut]:
    return await venues_service.search(session, auth.user, q, org_id)


@router.post("/venues", response_model=VenueOut, status_code=201, summary="Добавить площадку")
async def create_venue(body: VenueIn, auth: AuthDep, session: SessionDep, geo: GeoDep) -> VenueOut:
    return await venues_service.create(session, auth.user, body, geo)


@router.post("/media", response_model=MediaOut, status_code=201, summary="Загрузить обложку")
async def upload_media(
    file: UploadFile, auth: AuthDep, session: SessionDep, settings: SettingsDep
) -> MediaOut:
    # Читаем на байт больше лимита: так узнаём о превышении, не загружая весь файл.
    data = await file.read(media_service.MAX_BYTES + 1)
    if not data:
        raise AppError("empty_file", "Файл пустой", status_code=422)
    media = await media_service.upload(session, auth.user, data, settings.media_dir)
    return media_service.to_out(media)
