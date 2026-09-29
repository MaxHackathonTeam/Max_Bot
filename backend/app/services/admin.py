"""Очередь модератора и журнал аудита (§6, FR-ADM)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.orgs import VerificationRequest
from app.models.system import AuditLog, ModerationDecision
from app.models.users import User
from app.moderation import rules
from app.schemas.manage import (
    AdminAuthor,
    AdminEventCard,
    AuditItem,
    AuditPage,
    DecisionItem,
    QueueOut,
    QueueVerification,
    RuleFlag,
)
from app.services import event_editor
from app.services import moderation as moderation_service
from app.services import verification as verification_service

QUEUE_LIMIT = 20
AUDIT_LIMIT = 50


async def request_status(session: AsyncSession, kind: str, entity_id: int) -> str | None:
    """Статус заявки из уведомления модератору: e — событие, v — проверка организации."""
    item: Event | VerificationRequest | None = (
        await session.get(Event, entity_id)
        if kind == "e"
        else await session.get(VerificationRequest, entity_id)
    )
    return str(item.status) if item is not None else None


async def queue(
    session: AsyncSession,
    limit: int = QUEUE_LIMIT,
    kind: moderation_service.QueueFilter = "all",
) -> QueueOut:
    events = await moderation_service.queue_events(session, limit, kind)
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


async def event_card(session: AsyncSession, event_id: int) -> AdminEventCard:
    """Карточка события для модератора (вызывающий — админ, проверено в AdminDep)."""
    event, out, flags = await event_editor.admin_view(session, event_id)
    _, signals = rules.score(
        rules.EventData(
            title=event.title or "",
            description=event.description,
            short_description=event.short_description,
        )
    )
    author = await session.get(User, event.author_user_id) if event.author_user_id else None
    decisions = await session.scalars(
        select(ModerationDecision)
        .where(ModerationDecision.entity_type == "event", ModerationDecision.entity_id == event_id)
        .order_by(ModerationDecision.id.desc())
        .limit(AUDIT_LIMIT)
    )
    history = await audit_page(session, entity_type="event", entity_id=event_id, before_id=None)
    return AdminEventCard(
        event=out,
        author=(
            AdminAuthor(
                id=author.id,
                name=" ".join(p for p in (author.first_name, author.last_name) if p) or None,
                max_user_id=author.max_user_id,
            )
            if author
            else None
        ),
        flags=[
            *(RuleFlag(code=f.code, field=f.field, message=f.message, kind=f.kind) for f in flags),
            # Признаки подозрительности (rules.score): из-за них событие ждёт модератора.
            *(
                RuleFlag(code="suspicious", field="content", message=reason, kind="signal")
                for reason in signals
            ),
        ],
        decisions=[
            DecisionItem(
                id=d.id,
                created_at=d.created_at,
                actor_type=d.actor_type,
                actor_user_id=d.actor_user_id,
                verdict=d.verdict,
                reasons=d.reasons,
            )
            for d in decisions
        ],
        history=history.items,
    )


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
