"""Вход на сайте через MAX: код → подтверждение в боте → токен сайту (контракт API п. 3).

Код живёт в Redis 5 минут и расходуется один раз. Если сайт запросил код под гостевым
токеном, после подтверждения данные гостя переносятся в MAX-аккаунт (users.merge_guest).
"""

import json
import secrets
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.models.enums import AuditActor
from app.models.users import User
from app.services import audit
from app.services import users as users_service

CODE_TTL_S = 300
CODE_LENGTH = 6
# Без похожих символов: 0/O, 1/I/L.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
START_PREFIX = "login_"
_KEY = "weblogin:{code}"


@dataclass(frozen=True)
class WebCode:
    code: str
    deeplink: str
    expires_in: int


@dataclass(frozen=True)
class PollResult:
    status: Literal["pending", "confirmed", "expired"]
    user: User | None = None


def normalize(code: str) -> str | None:
    code = code.strip().upper()
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        return None
    return code


def code_from_start(payload: str | None) -> str | None:
    """`login_<code>` из диплинка или команды `/start login_<code>`."""
    if not payload:
        return None
    payload = payload.strip().removeprefix("/start").strip()
    if not payload.startswith(START_PREFIX):
        return None
    return normalize(payload[len(START_PREFIX) :])


async def create(
    session: AsyncSession, redis: Any, settings: Settings, guest: User | None
) -> WebCode:
    if not settings.max_bot_username:
        raise AppError("bot_unavailable", "Вход через MAX сейчас недоступен", 503)
    guest_id = guest.id if guest is not None and guest.max_user_id is None else None
    value = json.dumps({"status": "pending", "guest_user_id": guest_id})
    for _ in range(5):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if await redis.set(_KEY.format(code=code), value, ex=CODE_TTL_S, nx=True):
            break
    else:
        raise AppError("code_unavailable", "Не получилось выдать код, попробуй ещё раз", 503)
    await audit.record(
        session,
        action="auth.web_code",
        entity_type="user",
        entity_id=guest_id,
        actor_type=AuditActor.user if guest_id else AuditActor.system,
        actor_user_id=guest_id,
    )
    await session.commit()
    deeplink = f"https://max.ru/{settings.max_bot_username}?start={START_PREFIX}{code}"
    return WebCode(code=code, deeplink=deeplink, expires_in=CODE_TTL_S)


async def _load(redis: Any, code: str) -> dict[str, Any] | None:
    raw = await redis.get(_KEY.format(code=code))
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


async def confirm(session: AsyncSession, redis: Any, code: str, user: User) -> bool:
    """Нажатие «Подтвердить» в боте. False — код истёк или уже подтверждён."""
    data = await _load(redis, code)
    if data is None or data.get("status") != "pending":
        return False
    data.update(status="confirmed", user_id=user.id)
    if not await redis.set(_KEY.format(code=code), json.dumps(data), xx=True, keepttl=True):
        return False
    await audit.record(
        session,
        action="auth.web_code_confirm",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
    )
    await session.commit()
    return True


async def poll(session: AsyncSession, redis: Any, raw_code: str) -> PollResult:
    code = normalize(raw_code)
    data = await _load(redis, code) if code else None
    if code is None or data is None:
        return PollResult("expired")
    if data.get("status") != "confirmed":
        return PollResult("pending")
    # Одноразовый: токен получает тот, кто первым удалил ключ.
    if not await redis.delete(_KEY.format(code=code)):
        return PollResult("expired")
    user = await session.get(User, int(data["user_id"]))
    if user is None or user.deleted_at is not None:
        return PollResult("expired")
    guest_id = data.get("guest_user_id")
    guest = await session.get(User, int(guest_id)) if guest_id else None
    if guest is not None and guest.id != user.id:
        await users_service.merge_guest(session, guest, user)
    await audit.record(
        session,
        action="auth.web_login",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        diff={"merged_guest": guest.id if guest is not None else None},
    )
    await session.commit()
    return PollResult("confirmed", user)
