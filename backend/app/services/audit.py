"""Журнал аудита: каждое изменение сущностей пишется сюда (§10, CLAUDE.md).

Запись добавляется в текущую транзакцию — фиксируется вместе с самим изменением.
"""

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import AuditActor
from app.models.system import AuditLog

# Поля, значения которых не попадают в diff (ПДн и секреты).
_MASKED_FIELDS = frozenset({"phone", "email", "token", "password", "init_data", "home_point"})
_MASK = "***"


def _mask(diff: dict[str, Any] | None) -> dict[str, Any] | None:
    if diff is None:
        return None
    return {k: (_MASK if k in _MASKED_FIELDS and v is not None else v) for k, v in diff.items()}


def changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Diff вида {поле: [было, стало]} только по изменившимся полям."""
    return {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return str(value) if value is not None else None


async def record(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: int | None,
    actor_type: AuditActor = AuditActor.user,
    actor_user_id: int | None = None,
    diff: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        diff=_mask(diff),
        request_id=current_request_id(),
    )
    session.add(entry)
    await session.flush()
    return entry
