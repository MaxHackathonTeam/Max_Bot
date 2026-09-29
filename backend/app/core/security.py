"""Проверка initData мини-приложения MAX (§11.1) и JWT.

Алгоритм initData сверён с официальным клиентом max-bot-api-client-go (ValidateInitData):
secret = HMAC_SHA256(key="WebAppData", msg=bot_token);
hash = hex(HMAC_SHA256(key=secret, msg="\\n".join(sorted("k=v" без hash)))).
"""

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, unquote

import jwt

from app.core.config import Settings

JWT_ALGORITHM = "HS256"
_WEB_APP_DATA = b"WebAppData"
# Без JWT_SECRET вне прода — случайный секрет процесса (токены живут до рестарта).
_EPHEMERAL_JWT_SECRET = secrets.token_urlsafe(32)


class InitDataError(Exception):
    """initData не прошла проверку. Текст — для логов, клиенту уходит общий ответ."""


@dataclass(frozen=True)
class InitData:
    user: dict[str, Any]
    auth_date: datetime
    start_param: str | None = None
    query_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def max_user_id(self) -> int:
        return int(self.user["id"])


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(_WEB_APP_DATA, bot_token.encode(), hashlib.sha256).digest()


def data_check_string(params: dict[str, str]) -> str:
    # Как в Go-клиенте: сортируются готовые строки «k=v», а не ключи.
    return "\n".join(sorted(f"{k}={v}" for k, v in params.items() if k != "hash"))


def sign(params: dict[str, str], bot_token: str) -> str:
    """Подпись набора параметров initData (hex)."""
    return hmac.new(
        _secret_key(bot_token), data_check_string(params).encode(), hashlib.sha256
    ).hexdigest()


def _first_values(query: str) -> dict[str, str]:
    # Как url.Values.Get в Go-клиенте: при повторе ключа берётся первое значение.
    params: dict[str, str] = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        params.setdefault(key, value)
    return params


def parse_init_data(raw: str) -> dict[str, str]:
    raw = raw.strip()
    params = _first_values(raw)
    # Встречается initData, закодированная целиком ещё раз (hash%3D...): раскодируем один раз.
    if "hash" not in params and "%3D" in raw.upper():
        params = _first_values(unquote(raw))
    return params


def _parse_auth_date(value: str | None) -> datetime:
    if not value or not value.isdigit():
        raise InitDataError("auth_date отсутствует или некорректен")
    ts = int(value)
    if ts > 10**12:  # миллисекунды
        ts //= 1000
    return datetime.fromtimestamp(ts, tz=UTC)


def _parse_user(value: str | None) -> dict[str, Any]:
    if not value:
        raise InitDataError("user отсутствует")
    try:
        user = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InitDataError("user — некорректный JSON") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("user.id отсутствует")
    return user


def build_init_data(params: dict[str, str]) -> InitData:
    known = {"user", "auth_date", "start_param", "query_id", "hash"}
    return InitData(
        user=_parse_user(params.get("user")),
        auth_date=_parse_auth_date(params.get("auth_date")),
        start_param=params.get("start_param") or None,
        query_id=params.get("query_id") or None,
        extra={k: v for k, v in params.items() if k not in known},
    )


def validate_init_data(
    raw: str, bot_token: str, max_age_s: int, now: datetime | None = None
) -> InitData:
    params = parse_init_data(raw)
    received = params.get("hash")
    if not received:
        raise InitDataError("hash отсутствует")
    if not hmac.compare_digest(sign(params, bot_token), received.lower()):
        raise InitDataError("подпись не совпадает")
    data = build_init_data(params)
    now = now or datetime.now(UTC)
    age = (now - data.auth_date).total_seconds()
    if age > max_age_s:
        raise InitDataError("initData устарела")
    if age < -300:  # допускаем небольшой рассинхрон часов
        raise InitDataError("auth_date в будущем")
    return data


def _jwt_secret(settings: Settings) -> str:
    if settings.jwt_secret is not None:
        return settings.jwt_secret.get_secret_value()
    return _EPHEMERAL_JWT_SECRET


def create_access_token(
    user_id: int,
    settings: Settings,
    review_role: str | None = None,
    ttl: timedelta | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + (ttl or timedelta(hours=settings.jwt_ttl_hours))
    claims: dict[str, Any] = {"sub": str(user_id), "iat": now, "exp": expires_at}
    if review_role:
        claims["review_role"] = review_role
    return jwt.encode(claims, _jwt_secret(settings), algorithm=JWT_ALGORITHM), expires_at


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Бросает jwt.PyJWTError при неверной подписи или истёкшем сроке."""
    claims: dict[str, Any] = jwt.decode(
        token,
        _jwt_secret(settings),
        algorithms=[JWT_ALGORITHM],
        options={"require": ["sub", "exp", "iat"]},
    )
    return claims
