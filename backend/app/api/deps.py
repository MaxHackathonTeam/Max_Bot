"""Общие зависимости роутеров: настройки, сессия БД, текущий пользователь."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import decode_access_token
from app.models.users import User

_bearer = HTTPBearer(auto_error=False, description="JWT из POST /api/v1/auth/max")


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
