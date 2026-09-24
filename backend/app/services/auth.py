"""Вход: initData MAX, DEV_AUTH (локально), review-login для жюри (§11.1)."""

import hashlib
import hmac
import json
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    InitData,
    InitDataError,
    build_init_data,
    parse_init_data,
    validate_init_data,
)
from app.models.users import User
from app.services import users as users_service

log = structlog.get_logger(__name__)

REVIEW_ROLES = ("user", "org_owner_verified", "org_owner_unverified", "admin")


@dataclass(frozen=True)
class ReviewAccount:
    login: str
    password: str
    role: str

    @property
    def synthetic_max_user_id(self) -> int:
        # Отрицательный id не пересекается с настоящими пользователями MAX.
        digest = hashlib.sha256(f"review:{self.login}".encode()).hexdigest()
        return -int(digest[:12], 16)


def _invalid_init_data() -> AppError:
    return AppError(
        "invalid_init_data",
        "Не получилось проверить вход через MAX. Закрой и снова открой приложение",
        status_code=401,
    )


def _resolve_init_data(raw: str, settings: Settings) -> InitData:
    token = settings.max_bot_token.get_secret_value() if settings.max_bot_token else None
    if token:
        try:
            return validate_init_data(raw, token, settings.init_data_max_age_s)
        except InitDataError as exc:
            if not settings.dev_auth:
                log.info("init_data_rejected", reason=str(exc))
                raise _invalid_init_data() from exc
    if settings.dev_auth and not settings.is_prod:
        # DEV_AUTH: фейковый init_data вне MAX принимается без подписи.
        try:
            return build_init_data(parse_init_data(raw))
        except InitDataError as exc:
            raise _invalid_init_data() from exc
    raise AppError("auth_unavailable", "Вход временно недоступен: бот не настроен", 503)


async def login_with_init_data(
    session: AsyncSession, raw: str, settings: Settings
) -> tuple[User, InitData]:
    data = _resolve_init_data(raw, settings)
    user = await users_service.upsert_from_max(session, data.user)
    return user, data


def parse_review_accounts(settings: Settings) -> list[ReviewAccount]:
    if settings.review_accounts is None:
        return []
    try:
        raw = json.loads(settings.review_accounts.get_secret_value())
        return [
            ReviewAccount(login=str(a["login"]), password=str(a["password"]), role=str(a["role"]))
            for a in raw
            if a.get("role") in REVIEW_ROLES
        ]
    except (ValueError, TypeError, KeyError, AttributeError):
        log.error("review_accounts_invalid")
        return []


async def review_login(
    session: AsyncSession, login: str, password: str, settings: Settings
) -> tuple[User, str]:
    if not settings.review_mode:
        raise AppError("not_found", "Не найдено", status_code=404)
    matched: ReviewAccount | None = None
    for account in parse_review_accounts(settings):
        # Проверяем все учётки, сравнение за постоянное время.
        login_ok = hmac.compare_digest(account.login.encode(), login.encode())
        password_ok = hmac.compare_digest(account.password.encode(), password.encode())
        if login_ok and password_ok:
            matched = account
    if matched is None:
        raise AppError("invalid_credentials", "Неверный логин или пароль", status_code=401)
    user = await users_service.upsert_from_max(
        session,
        {"id": matched.synthetic_max_user_id, "first_name": f"Проверка ({matched.role})"},
    )
    return user, matched.role
