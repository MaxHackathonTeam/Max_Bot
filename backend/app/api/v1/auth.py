"""Вход в мини-приложение (§11.1)."""

from fastapi import APIRouter

from app.api.deps import SessionDep, SettingsDep
from app.core.security import create_access_token
from app.schemas.users import AuthMaxIn, ReviewLoginIn, TokenOut
from app.services import auth as auth_service
from app.services import users as users_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/max", response_model=TokenOut, summary="Вход по initData MAX Bridge")
async def auth_max(body: AuthMaxIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
    user, data = await auth_service.login_with_init_data(session, body.init_data, settings)
    token, expires_at = create_access_token(user.id, settings)
    return TokenOut(
        access_token=token,
        expires_at=expires_at,
        user=await users_service.to_me_out(session, user, settings),
        start_param=data.start_param,
    )


@router.post(
    "/review-login",
    response_model=TokenOut,
    summary="Вход тестовых учёток жюри (только REVIEW_MODE)",
)
async def review_login(body: ReviewLoginIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
    user, role = await auth_service.review_login(session, body.login, body.password, settings)
    token, expires_at = create_access_token(user.id, settings, review_role=role)
    return TokenOut(
        access_token=token,
        expires_at=expires_at,
        user=await users_service.to_me_out(session, user, settings, role),
    )
