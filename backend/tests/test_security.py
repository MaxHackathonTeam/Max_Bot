"""initData (§11.1) — кейсы повторяют тесты официального max-bot-api-client-go."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlencode

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.security import (
    InitDataError,
    create_access_token,
    data_check_string,
    decode_access_token,
    sign,
    validate_init_data,
)
from tests.helpers import BOT_TOKEN, make_init_data

DAY = 24 * 3600
AUTH_DATE = 1758650000
NOW = datetime.fromtimestamp(AUTH_DATE, tz=UTC) + timedelta(minutes=5)

# Эталон: параметры из TestValidateInitData Go-клиента с фиксированным auth_date.
# Hash посчитан независимо от кода приложения по алгоритму generateTestHash (Go).
REFERENCE_PARAMS = {
    "user": '{"id":123456,"first_name":"Test","last_name":"User"}',
    "chat_instance": "test_chat_123",
    "chat_type": "private",
    "start_param": "test_start",
    "auth_date": str(AUTH_DATE),
}
REFERENCE_HASH = "6a2f11fa309e4d499d2db7ed0976dd1b655164d03215d3d977aa5a2ba09ce686"


def _reference_raw(**overrides: str) -> str:
    return urlencode({**REFERENCE_PARAMS, "hash": REFERENCE_HASH, **overrides})


def _settings(secret: str) -> Settings:
    return Settings(_env_file=None, env="test", jwt_secret=SecretStr(secret))


def test_reference_vector() -> None:
    assert data_check_string(REFERENCE_PARAMS) == (
        "auth_date=1758650000\nchat_instance=test_chat_123\nchat_type=private\n"
        'start_param=test_start\nuser={"id":123456,"first_name":"Test","last_name":"User"}'
    )
    assert sign(REFERENCE_PARAMS, BOT_TOKEN) == REFERENCE_HASH

    data = validate_init_data(_reference_raw(), BOT_TOKEN, DAY, now=NOW)
    assert data.max_user_id == 123456
    assert data.user["first_name"] == "Test"
    assert data.start_param == "test_start"
    assert data.extra == {"chat_instance": "test_chat_123", "chat_type": "private"}


def test_algorithm_matches_spec() -> None:
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    check = data_check_string(REFERENCE_PARAMS).encode()
    assert hmac.new(secret, check, hashlib.sha256).hexdigest() == REFERENCE_HASH


def test_fully_url_encoded_string() -> None:
    data = validate_init_data(quote(_reference_raw(), safe=""), BOT_TOKEN, DAY, now=NOW)
    assert data.max_user_id == 123456


def test_uppercase_hash_accepted() -> None:
    raw = _reference_raw(hash=REFERENCE_HASH.upper())
    assert validate_init_data(raw, BOT_TOKEN, DAY, now=NOW).max_user_id == 123456


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(urlencode(REFERENCE_PARAMS), id="missing_hash"),
        pytest.param(_reference_raw(hash="0" * 64), id="invalid_hash"),
        pytest.param(
            _reference_raw(user='{"id":999999,"first_name":"Test","last_name":"User"}'),
            id="tampered_user",
        ),
        pytest.param(_reference_raw(auth_date=str(AUTH_DATE + 1)), id="tampered_auth_date"),
        pytest.param(_reference_raw(start_param="ev_1"), id="tampered_start_param"),
        pytest.param(
            _reference_raw(user=json.dumps({"first_name": "Test", "id": 123456})),
            id="reordered_user_json",
        ),
        pytest.param("", id="empty"),
    ],
)
def test_rejected(raw: str) -> None:
    with pytest.raises(InitDataError):
        validate_init_data(raw, BOT_TOKEN, DAY, now=NOW)


def test_wrong_token_rejected() -> None:
    with pytest.raises(InitDataError):
        validate_init_data(_reference_raw(), "other_token", DAY, now=NOW)


def test_multiple_hash_values_first_used() -> None:
    raw = _reference_raw() + "&hash=" + "0" * 64
    assert validate_init_data(raw, BOT_TOKEN, DAY, now=NOW).max_user_id == 123456
    raw = urlencode({**REFERENCE_PARAMS, "hash": "0" * 64}) + "&hash=" + REFERENCE_HASH
    with pytest.raises(InitDataError):
        validate_init_data(raw, BOT_TOKEN, DAY, now=NOW)


def test_extra_platform_params_and_special_chars() -> None:
    token = "tok:with/special+chars=&"
    user = {
        "id": 42,
        "first_name": "Анна & Ко",
        "last_name": "O'Нил",
        "photo_url": "https://x/y?a=b",
    }
    raw = make_init_data(
        user, token=token, auth_date=AUTH_DATE, web_app_platform="ios", query_id="q-1"
    )
    data = validate_init_data(raw, token, DAY, now=NOW)
    assert data.user["first_name"] == "Анна & Ко"
    assert data.query_id == "q-1"
    assert data.extra["web_app_platform"] == "ios"


def test_expired_and_future() -> None:
    old = make_init_data({"id": 1}, auth_date=AUTH_DATE - DAY - 10)
    with pytest.raises(InitDataError, match="устарела"):
        validate_init_data(old, BOT_TOKEN, DAY, now=NOW)

    future = make_init_data({"id": 1}, auth_date=AUTH_DATE + 3600)
    with pytest.raises(InitDataError, match="будущем"):
        validate_init_data(future, BOT_TOKEN, DAY, now=NOW)


def test_milliseconds_auth_date() -> None:
    raw = make_init_data({"id": 1}, auth_date=AUTH_DATE * 1000)
    assert validate_init_data(raw, BOT_TOKEN, DAY, now=NOW).auth_date.year == 2025


def test_missing_user_id_rejected() -> None:
    raw = make_init_data({"first_name": "Без id"}, auth_date=AUTH_DATE)
    with pytest.raises(InitDataError):
        validate_init_data(raw, BOT_TOKEN, DAY, now=NOW)


def test_jwt_roundtrip_and_tamper() -> None:
    token, expires_at = create_access_token(5, _settings("s" * 40), review_role="admin")
    claims = decode_access_token(token, _settings("s" * 40))
    assert claims["sub"] == "5"
    assert claims["review_role"] == "admin"
    assert expires_at > datetime.now(UTC) + timedelta(hours=11)
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token, _settings("t" * 40))
