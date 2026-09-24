"""Включает вход для роли приложения после миграций: `python -m app.db.roles`.

Роль `afisha_app` создаёт миграция (NOLOGIN, без DDL, без UPDATE/DELETE на audit_log).
Пароль берётся из APP_DB_PASSWORD и в репозиторий не попадает.
"""

import asyncio

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging

APP_ROLE = "afisha_app"

log = structlog.get_logger(__name__)


async def enable_app_role(database_url: str, password: str) -> None:
    # ALTER ROLE не принимает bind-параметры — экранируем кавычки вручную.
    quoted = password.replace("'", "''")
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{quoted}'"))
    finally:
        await engine.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.app_db_password is None:
        log.warning("app_role_skipped", reason="APP_DB_PASSWORD не задан")
        return
    await enable_app_role(
        settings.alembic_database_url, settings.app_db_password.get_secret_value()
    )
    log.info("app_role_enabled", role=APP_ROLE)


if __name__ == "__main__":
    asyncio.run(main())
