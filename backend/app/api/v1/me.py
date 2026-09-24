"""Профиль текущего пользователя и согласия (FR-ONB)."""

from typing import Literal

from fastapi import APIRouter, Response

from app.api.deps import AuthDep, SessionDep, SettingsDep
from app.schemas.events import SavedItem
from app.schemas.users import ConsentsIn, MeOut, MeUpdate
from app.services import saved as saved_service
from app.services import users as users_service

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeOut, summary="Мой профиль")
async def get_me(auth: AuthDep, session: SessionDep, settings: SettingsDep) -> MeOut:
    return await users_service.to_me_out(session, auth.user, settings, auth.review_role)


@router.patch("", response_model=MeOut, summary="Изменить настройки профиля")
async def patch_me(
    body: MeUpdate, auth: AuthDep, session: SessionDep, settings: SettingsDep
) -> MeOut:
    user = await users_service.update_profile(session, auth.user, body)
    return await users_service.to_me_out(session, user, settings, auth.review_role)


@router.delete("", status_code=204, summary="Удалить мои данные")
async def delete_me(auth: AuthDep, session: SessionDep) -> Response:
    await users_service.delete_user_data(session, auth.user)
    return Response(status_code=204)


@router.post("/consents", response_model=MeOut, summary="Принять документы")
async def accept_consents(
    body: ConsentsIn, auth: AuthDep, session: SessionDep, settings: SettingsDep
) -> MeOut:
    await users_service.accept_consents(session, auth.user, body.docs)
    return await users_service.to_me_out(session, auth.user, settings, auth.review_role)


@router.get("/saved", response_model=list[SavedItem], summary="Мои «Пойду»")
async def my_saved(
    auth: AuthDep, session: SessionDep, when: Literal["upcoming", "past"] = "upcoming"
) -> list[SavedItem]:
    return await saved_service.list_saved(session, auth.user, when)
