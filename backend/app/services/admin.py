"""Очередь модератора и журнал аудита (§6, FR-ADM)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system import AuditLog
from app.schemas.manage import AuditItem, AuditPage, QueueOut, QueueVerification
from app.services import moderation as moderation_service
from app.services import verification as verification_service

QUEUE_LIMIT = 20
AUDIT_LIMIT = 50


async def queue(session: AsyncSession, limit: int = QUEUE_LIMIT) -> QueueOut:
    events = await moderation_service.queue_events(session, limit)
    verifications = [
        QueueVerification(
            id=request.id,
            org_id=org.id,
            org_name=org.name,
            method=request.method,
            inn=request.inn,
            site_url=request.site_url,
            steps=[step.model_dump() for step in verification_service.steps_of(request)],
            created_at=request.created_at,
        )
        for request, org in await verification_service.pending_for_admin(session, limit)
    ]
    return QueueOut(events=events, verifications=verifications)


async def audit_page(
    session: AsyncSession,
    *,
    entity_type: str | None,
    entity_id: int | None,
    before_id: int | None,
    limit: int = AUDIT_LIMIT,
) -> AuditPage:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if before_id is not None:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = list(await session.scalars(stmt))
    more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(
        items=[_item(row) for row in rows],
        next_before_id=rows[-1].id if more and rows else None,
    )


def _item(row: AuditLog) -> AuditItem:
    diff: dict[str, Any] | None = row.diff
    return AuditItem(
        id=row.id,
        created_at=row.created_at,
        actor_type=row.actor_type,
        actor_user_id=row.actor_user_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        diff=diff,
        request_id=row.request_id,
    )
