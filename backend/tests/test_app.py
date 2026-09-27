import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel, SecretStr, ValidationError

from app.api import health
from app.core.config import Settings
from app.core.errors import AppError


async def test_health_ok(client: AsyncClient) -> None:
    for path in ("/health", "/api/v1/health"):
        r = await client.get(path)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


async def test_request_id_generated_and_echoed(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert len(r.headers["X-Request-Id"]) == 32

    r = await client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["X-Request-Id"] == "abc-123"


async def test_invalid_request_id_replaced(client: AsyncClient) -> None:
    r = await client.get("/health", headers={"X-Request-Id": "bad id\twith spaces"})
    assert r.headers["X-Request-Id"] != "bad id\twith spaces"


async def test_not_found_error_format(client: AsyncClient) -> None:
    r = await client.get("/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Не найдено", "details": {}}}
    assert "X-Request-Id" in r.headers


async def test_validation_and_app_errors(app: FastAPI, client: AsyncClient) -> None:
    class Body(BaseModel):
        n: int

    @app.post("/_t/validate")
    async def validate(body: Body) -> dict[str, int]:
        return {"n": body.n}

    @app.get("/_t/app-error")
    async def app_error() -> None:
        raise AppError("org_not_verified", "Организация не проверена", 403, {"org_id": 1})

    @app.get("/_t/boom")
    async def boom() -> None:
        raise RuntimeError("секрет не должен утечь")

    r = await client.post("/_t/validate", json={"n": "x"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]["fields"][0]["loc"] == ["body", "n"]

    r = await client.get("/_t/app-error")
    assert r.status_code == 403
    assert r.json()["error"] == {
        "code": "org_not_verified",
        "message": "Организация не проверена",
        "details": {"org_id": 1},
    }

    r = await client.get("/_t/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "секрет" not in r.text
    assert "X-Request-Id" in r.headers


async def test_ready_reports_failed_dependencies(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def fail() -> None:
        raise ConnectionError

    monkeypatch.setattr(health, "_check_db", ok)
    monkeypatch.setattr(health, "_check_redis", fail)
    r = await client.get("/ready")
    assert r.status_code == 503
    assert r.json()["error"]["details"]["checks"] == {"db": "ok", "redis": "fail"}

    monkeypatch.setattr(health, "_check_redis", ok)
    r = await client.get("/ready")
    assert r.status_code == 200


def test_prod_with_dev_auth_refuses_to_start() -> None:
    with pytest.raises(ValidationError, match="DEV_AUTH"):
        Settings(env="prod", dev_auth=True, jwt_secret=SecretStr("x" * 40))
    Settings(env="prod", dev_auth=False, jwt_secret=SecretStr("x" * 40))
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(_env_file=None, env="prod", dev_auth=False)
    Settings(env="local", dev_auth=True)


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_MAX_USER_IDS", "1, 2,3")
    monkeypatch.setenv("MAX_BOT_TOKEN", "")
    monkeypatch.setenv("DEV_AUTH", "")
    s = Settings(_env_file=None)
    assert s.admin_max_user_ids == [1, 2, 3]
    assert s.max_bot_token is None
    assert s.dev_auth is False
