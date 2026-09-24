"""POST /auth/max, /auth/review-login, /me — с настоящей БД (TEST_DATABASE_URL)."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import create_app
from app.models.system import AuditLog
from app.models.users import Consent, User
from tests.helpers import make_init_data, random_max_id


@asynccontextmanager
async def _client_for(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await app.state.db.kw["bind"].dispose()


async def _login(client: httpx.AsyncClient, user: dict[str, Any], **extra: str) -> dict[str, Any]:
    raw = make_init_data(user, **extra)  # type: ignore[arg-type]  # только строковые параметры
    r = await client.post("/api/v1/auth/max", json={"init_data": raw})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _audit_actions(session: AsyncSession, user_id: int) -> list[str]:
    rows = await session.scalars(
        select(AuditLog.action)
        .where(AuditLog.entity_type == "user", AuditLog.entity_id == user_id)
        .order_by(AuditLog.id)
    )
    return list(rows)


async def test_auth_max_creates_user_and_token(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    max_id = random_max_id()
    body = await _login(
        db_client, {"id": max_id, "first_name": "Анна", "username": "anna"}, start_param="ev_42"
    )
    assert body["token_type"] == "bearer"
    assert body["start_param"] == "ev_42"
    me = body["user"]
    assert me["max_user_id"] == max_id
    assert me["first_name"] == "Анна"
    assert me["needs_onboarding"] is True
    assert me["is_admin"] is False
    assert {c["doc"] for c in me["consents"]} == {"terms", "privacy", "org_pd"}

    r = await db_client.get("/api/v1/me", headers=_bearer(body["access_token"]))
    assert r.status_code == 200
    assert r.json()["first_name"] == "Анна"
    assert await _audit_actions(db_session, me["id"]) == ["user.create"]


async def test_auth_max_repeat_login_updates_profile(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    max_id = random_max_id()
    first = await _login(db_client, {"id": max_id, "first_name": "Иван"})
    second = await _login(db_client, {"id": max_id, "first_name": "Ваня"})
    assert first["user"]["id"] == second["user"]["id"]
    assert second["user"]["first_name"] == "Ваня"
    assert await _audit_actions(db_session, first["user"]["id"]) == [
        "user.create",
        "user.sync_max_profile",
    ]


async def test_auth_max_bad_signature_401(db_client: httpx.AsyncClient) -> None:
    raw = make_init_data({"id": random_max_id()}, token="other_token")
    r = await db_client.post("/api/v1/auth/max", json={"init_data": raw})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_init_data"


async def test_auth_max_without_bot_token_503(db_settings: Settings) -> None:
    settings = db_settings.model_copy(update={"max_bot_token": None})
    async with _client_for(settings) as client:
        raw = make_init_data({"id": random_max_id()})
        r = await client.post("/api/v1/auth/max", json={"init_data": raw})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "auth_unavailable"


async def test_dev_auth_accepts_unsigned_init_data(db_settings: Settings) -> None:
    settings = db_settings.model_copy(update={"max_bot_token": None, "dev_auth": True})
    user = json.dumps({"id": random_max_id(), "first_name": "Dev"})
    raw = urlencode({"user": user, "auth_date": "1758650000", "hash": "dev"})
    async with _client_for(settings) as client:
        r = await client.post("/api/v1/auth/max", json={"init_data": raw})
    assert r.status_code == 200
    assert r.json()["user"]["first_name"] == "Dev"


async def test_admin_flag_from_env(db_client: httpx.AsyncClient) -> None:
    body = await _login(db_client, {"id": 777, "first_name": "Админ"})
    assert body["user"]["is_admin"] is True


async def test_me_requires_token(db_client: httpx.AsyncClient) -> None:
    r = await db_client.get("/api/v1/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    r = await db_client.get("/api/v1/me", headers=_bearer("garbage"))
    assert r.status_code == 401


async def test_patch_me_and_consents(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    body = await _login(db_client, {"id": random_max_id(), "first_name": "Оля"})
    headers = _bearer(body["access_token"])

    r = await db_client.patch(
        "/api/v1/me",
        json={"radius_km": 30, "interests": ["music", "kids", "music"], "birth_year": 1990},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["radius_km"] == 30
    assert me["interests"] == ["music", "kids"]
    assert me["birth_year"] == 1990

    r = await db_client.patch("/api/v1/me", json={"radius_km": 7}, headers=headers)
    assert r.status_code == 422
    r = await db_client.patch("/api/v1/me", json={"locality_id": 999_999_999}, headers=headers)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "locality_not_found"

    for _ in range(2):  # повторное принятие идемпотентно
        r = await db_client.post(
            "/api/v1/me/consents", json={"docs": ["terms", "privacy"]}, headers=headers
        )
        assert r.status_code == 200
    states = {c["doc"]: c["accepted"] for c in r.json()["consents"]}
    assert states == {"terms": True, "privacy": True, "org_pd": False}
    assert r.json()["needs_onboarding"] is True  # населённый пункт ещё не выбран

    user_id = body["user"]["id"]
    consents = await db_session.scalars(select(Consent).where(Consent.user_id == user_id))
    assert len(list(consents)) == 2
    assert "user.update_profile" in await _audit_actions(db_session, user_id)


async def test_delete_me_anonymizes(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    max_id = random_max_id()
    body = await _login(db_client, {"id": max_id, "first_name": "Пётр", "last_name": "П."})
    headers = _bearer(body["access_token"])

    r = await db_client.delete("/api/v1/me", headers=headers)
    assert r.status_code == 204

    user = await db_session.get(User, body["user"]["id"])
    assert user is not None
    assert user.deleted_at is not None
    assert (user.max_user_id, user.first_name, user.last_name) == (None, None, None)
    assert "user.delete_data" in await _audit_actions(db_session, user.id)

    # Старый токен больше не действует, повторный вход — новый пользователь.
    assert (await db_client.get("/api/v1/me", headers=headers)).status_code == 401
    again = await _login(db_client, {"id": max_id, "first_name": "Пётр"})
    assert again["user"]["id"] != body["user"]["id"]


REVIEW_ACCOUNTS = json.dumps(
    [
        {"login": "jury_admin", "password": "pass-admin-1", "role": "admin"},
        {"login": "jury_user", "password": "pass-user-1", "role": "user"},
    ]
)


async def test_review_login_disabled_404(db_client: httpx.AsyncClient) -> None:
    r = await db_client.post(
        "/api/v1/auth/review-login", json={"login": "jury_admin", "password": "pass-admin-1"}
    )
    assert r.status_code == 404


async def test_review_login(db_settings: Settings) -> None:
    settings = db_settings.model_copy(
        update={"review_mode": True, "review_accounts": SecretStr(REVIEW_ACCOUNTS)}
    )
    async with _client_for(settings) as client:
        r = await client.post(
            "/api/v1/auth/review-login", json={"login": "jury_admin", "password": "wrong"}
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"

        r = await client.post(
            "/api/v1/auth/review-login", json={"login": "jury_admin", "password": "pass-admin-1"}
        )
        assert r.status_code == 200
        assert r.json()["user"]["is_admin"] is True
        me = await client.get("/api/v1/me", headers=_bearer(r.json()["access_token"]))
        assert me.json()["is_admin"] is True
        assert me.json()["max_user_id"] < 0

        r = await client.post(
            "/api/v1/auth/review-login", json={"login": "jury_user", "password": "pass-user-1"}
        )
        assert r.json()["user"]["is_admin"] is False
