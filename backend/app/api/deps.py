"""Общие зависимости роутеров: настройки, сессия БД, текущий пользователь."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.jobs import JobQueue
from app.core.security import decode_access_token
from app.models.users import User
from app.services import users as users_service
from app.services.notify import Notifier, QueuedNotifier

_bearer = HTTPBearer(auto_error=False, description="JWT из POST /api/v1/auth/max или /auth/guest")


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True)
class Auth:
    user: User
    # Роль учётки жюри (REVIEW_MODE), для обычных пользователей — None.
    review_role: str | None = None


def _unauthorized(message: str = "Нужна авторизация") -> HTTPException:
    return HTTPException(401, detail=message, headers={"WWW-Authenticate": "Bearer"})


async def current_auth(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Auth:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials, settings)
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise _unauthorized("Сессия истекла, открой приложение заново") from exc
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise _unauthorized("Сессия истекла, открой приложение заново")
    review_role = claims.get("review_role")
    return Auth(user=user, review_role=review_role if isinstance(review_role, str) else None)


AuthDep = Annotated[Auth, Depends(current_auth)]


async def optional_auth(
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Auth | None:
    """Для публичных ручек: пользователь, если токен есть и валиден, иначе None."""
    if credentials is None:
        return None
    try:
        return await current_auth(session, settings, credentials)
    except HTTPException:
        return None


OptionalAuthDep = Annotated[Auth | None, Depends(optional_auth)]


def get_jobs(request: Request) -> JobQueue:
    jobs: JobQueue = request.app.state.jobs
    return jobs


JobsDep = Annotated[JobQueue, Depends(get_jobs)]


def get_notifier(jobs: JobsDep) -> Notifier:
    # Из API сообщения только ставятся в очередь: отправляет воркер.
    return QueuedNotifier(jobs)


NotifierDep = Annotated[Notifier, Depends(get_notifier)]


def is_admin(auth: Auth, settings: Settings) -> bool:
    return users_service.is_admin(auth.user, settings, auth.review_role)


async def require_admin(auth: AuthDep, settings: SettingsDep) -> Auth:
    if not is_admin(auth, settings):
        raise AppError("forbidden", "Раздел только для модераторов", status_code=403)
    return auth


AdminDep = Annotated[Auth, Depends(require_admin)]
