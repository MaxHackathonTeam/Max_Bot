import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  регистрирует модели в метаданных
from app.core.config import get_settings
from app.db.base import Base

target_metadata = Base.metadata


def _include_name(name: str | None, type_: str, parent_names: object) -> bool:
    # В образе postgis есть служебные таблицы (tiger, topology, spatial_ref_sys) —
    # autogenerate сравнивает только наши таблицы.
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().alembic_database_url,
        target_metadata=target_metadata,
        include_name=_include_name,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, include_name=_include_name
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().alembic_database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
