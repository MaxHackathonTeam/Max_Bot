"""Ручной запуск импортов для администратора."""

from fastapi import APIRouter

from app.api.deps import AdminDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.sources.importer import run_import
from app.sources.proculture import ProCultureSource

router = APIRouter(prefix="/admin/imports", tags=["admin"])


@router.post("/{source}/run", summary="Запустить импорт источника")
async def run(
    source: str, _admin: AdminDep, session: SessionDep, settings: SettingsDep
) -> dict[str, int]:
    if source != "proculture":
        raise AppError("unknown_source", "Источник импорта не поддерживается", status_code=404)
    adapter = ProCultureSource(
        settings.proculture_api_key.get_secret_value() if settings.proculture_api_key else None
    )
    try:
        return await run_import(session, adapter, [])
    finally:
        await adapter.aclose()
