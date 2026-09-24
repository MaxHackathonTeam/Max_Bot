"""audit_log: роль приложения может только добавлять записи (§10)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.enums import AuditActor
from app.services import audit


async def _entry_id(session: AsyncSession) -> int:
    entry = await audit.record(
        session,
        action="test.insert",
        entity_type="test",
        entity_id=1,
        actor_type=AuditActor.system,
        diff={"password": "secret", "name": "ok"},
    )
    await session.commit()
    return entry.id


async def test_app_role_can_insert_and_masks_secrets(db_session: AsyncSession) -> None:
    entry_id = await _entry_id(db_session)
    diff = await db_session.scalar(
        text("SELECT diff FROM audit_log WHERE id = :id"), {"id": entry_id}
    )
    assert diff == {"password": "***", "name": "ok"}


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_log SET action = 'hacked' WHERE id = :id",
        "DELETE FROM audit_log WHERE id = :id",
        "TRUNCATE audit_log",
    ],
)
async def test_app_role_cannot_modify_audit_log(db_session: AsyncSession, sql: str) -> None:
    entry_id = await _entry_id(db_session)
    with pytest.raises(DBAPIError, match="permission denied"):
        await db_session.execute(text(sql), {"id": entry_id})
    await db_session.rollback()
    action = await db_session.scalar(
        text("SELECT action FROM audit_log WHERE id = :id"), {"id": entry_id}
    )
    assert action == "test.insert"


async def test_trigger_blocks_even_owner(owner_database_url: str) -> None:
    engine = create_async_engine(owner_database_url)
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="audit_log"):
                await conn.execute(text("DELETE FROM audit_log"))
    finally:
        await engine.dispose()
