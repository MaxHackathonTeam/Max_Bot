import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.jobs import MemoryJobQueue
from app.main import create_app
from tests.helpers import BOT_TOKEN, JWT_SECRET, WEBHOOK_SECRET

BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_ROLE_PASSWORD = "afisha_app_test"


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(env="test"))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Тесты с настоящей БД (Postgres + PostGIS) ---
# TEST_DATABASE_URL — владелец БД, например postgresql+asyncpg://afisha:afisha@localhost:55432/afisha.
# На каждую сессию pytest создаётся отдельная база, миграции применяются как в compose,
# а приложение ходит под ролью afisha_app — так проверяются и права роли.


def _plain_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


async def _admin_exec(url: str, sql: str) -> None:
    conn = await asyncpg.connect(_plain_dsn(url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def owner_database_url() -> Iterator[str]:
    base_url = os.environ.get("TEST_DATABASE_URL")
    if not base_url:
        pytest.skip("TEST_DATABASE_URL не задан — тесты с БД пропущены")
    name = f"afisha_test_{uuid.uuid4().hex[:8]}"
    asyncio.run(_admin_exec(base_url, f'CREATE DATABASE "{name}"'))
    owner_url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    env = {
        **os.environ,
        "MIGRATE_DATABASE_URL": owner_url,
        "DATABASE_URL": owner_url,
        "APP_DB_PASSWORD": APP_ROLE_PASSWORD,
    }
    for cmd in (["alembic", "upgrade", "head"], ["app.db.roles"]):
        args = [sys.executable, "-m", *cmd]
        subprocess.run(args, cwd=BACKEND_DIR, env=env, check=True, capture_output=True)
    try:
        yield owner_url
    finally:
        asyncio.run(_admin_exec(base_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def app_database_url(owner_database_url: str) -> str:
    url = make_url(owner_database_url).set(username="afisha_app", password=APP_ROLE_PASSWORD)
    return url.render_as_string(hide_password=False)


@pytest.fixture
def db_settings(app_database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        database_url=app_database_url,
        max_bot_token=SecretStr(BOT_TOKEN),
        max_bot_username="afisha_test_bot",
        max_webhook_secret=SecretStr(WEBHOOK_SECRET),
        jwt_secret=SecretStr(JWT_SECRET),
        admin_max_user_ids=[777],
        media_dir=str(tmp_path / "media"),
    )


@pytest.fixture
async def db_app(db_settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(db_settings)
    # Никаких сетевых геокодеров в тестах; нужные тесты подставляют фейковый.
    app.state.geo = None
    # Задачи копятся в памяти (тест выполняет их сам), реестр ЕГРЮЛ — фейковый или нет.
    app.state.jobs = MemoryJobQueue()
    app.state.registry = None
    yield app
    await app.state.db.kw["bind"].dispose()


@pytest.fixture
async def db_client(db_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=db_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def db_session(db_app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with db_app.state.db() as session:
        yield session
