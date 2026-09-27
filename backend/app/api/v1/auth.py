"""Вход: мини-приложение MAX (§11.1), гость сайта и вход на сайте через код из бота."""

from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import OptionalAuthDep, SessionDep, SettingsDep
from app.core.errors import AppError
from app.core.security import create_access_token
from app.schemas.users import (
    AuthMaxIn,
    ReviewLoginIn,
    TokenOut,
    WebCodeOut,
    WebCodePending,
    WebCodePollIn,
)
from app.services import auth as auth_service
from app.services import users as users_service
from app.services import web_login

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


@router.post("/guest", response_model=TokenOut, summary="Гостевой вход на сайте без MAX")
async def auth_guest(session: SessionDep, settings: SettingsDep) -> TokenOut:
    user = await users_service.create_guest(session)
    token, expires_at = create_access_token(
        user.id, settings, ttl=timedelta(days=settings.guest_jwt_ttl_days)
    )
    return TokenOut(
        access_token=token,
        expires_at=expires_at,
        user=await users_service.to_me_out(session, user, settings),
    )


def _redis(request: Request) -> object:
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        raise AppError("bot_unavailable", "Вход через MAX сейчас недоступен", 503)
    return redis


@router.post("/web-code", response_model=WebCodeOut, summary="Код для входа на сайте через MAX")
async def web_code(
    request: Request, session: SessionDep, settings: SettingsDep, auth: OptionalAuthDep
) -> WebCodeOut:
    code = await web_login.create(
        session, _redis(request), settings, auth.user if auth is not None else None
    )
    return WebCodeOut(code=code.code, deeplink=code.deeplink, expires_in=code.expires_in)


@router.post(
    "/web-code/poll",
    response_model=TokenOut,
    summary="Проверить, подтверждён ли код в боте",
    responses={
        202: {"model": WebCodePending, "description": "Код ещё не подтверждён"},
        410: {"description": "Код истёк или уже использован"},
    },
)
async def web_code_poll(
    body: WebCodePollIn, request: Request, session: SessionDep, settings: SettingsDep
) -> TokenOut | JSONResponse:
    result = await web_login.poll(session, _redis(request), body.code)
    if result.status == "pending":
        return JSONResponse(WebCodePending().model_dump(), status_code=202)
    if result.user is None:
        raise AppError("code_expired", "Код истёк — запроси новый", 410)
    token, expires_at = create_access_token(result.user.id, settings)
    return TokenOut(
        access_token=token,
        expires_at=expires_at,
        user=await users_service.to_me_out(session, result.user, settings),
    )
