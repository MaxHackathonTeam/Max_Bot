"""Модерация событий (§6): решения правил и админа, жалобы, очередь.

Каждое решение пишется в moderation_decisions и audit_log.
"""

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.core.errors import AppError
from app.models.engagement import Report
from app.models.enums import (
    AuditActor,
    EventStatus,
    ModerationActor,
    ModerationVerdict,
    OrgRole,
    TrustTier,
)
from app.models.events import Event, EventSession
from app.models.orgs import Organization, OrgMember
from app.models.system import ModerationDecision
from app.models.users import User
from app.moderation import rules
from app.moderation.rules import Violation
from app.schemas.manage import QueueEvent, ReportIn
from app.services import audit
from app.services.events import utcnow
from app.services.notify import Notifier

REPORTS_TO_HIDE = 3


@dataclass(frozen=True)
class Outcome:
    status: str
    notify_text: str | None


async def recipients(session: AsyncSession, event: Event) -> list[int]:
    """Кому сообщать о решении: автор, иначе владельцы организации."""
    if event.author_user_id is not None:
        return [event.author_user_id]
    if event.organization_id is None:
        return []
    return list(
        await session.scalars(
            select(OrgMember.user_id).where(
                OrgMember.org_id == event.organization_id, OrgMember.role == OrgRole.owner
            )
        )
    )


async def notify_owner(session: AsyncSession, notifier: Notifier, event: Event, text: str) -> None:
    # Опубликованное — карточка, остальное автор правит в черновике.
    section = "ev" if event.status == EventStatus.published else "draft"
    for user_id in await recipients(session, event):
        await notifier.send(user_id, text, f"{section}_{event.id}")


async def record_decision(
    session: AsyncSession,
    event: Event,
    *,
    actor: ModerationActor,
    verdict: ModerationVerdict,
    reasons: Any = None,
    confidence: float | None = None,
    actor_user_id: int | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    status_before: str | None = None,
) -> None:
    session.add(
        ModerationDecision(
            entity_type="event",
            entity_id=event.id,
            actor_type=actor,
            actor_user_id=actor_user_id,
            verdict=verdict,
            confidence=confidence,
            reasons=reasons,
            model=model,
            prompt_version=prompt_version,
        )
    )
    audit_actor = {
        ModerationActor.rules: AuditActor.system,
        ModerationActor.llm: AuditActor.llm,  # legacy: решения прошлых версий
        ModerationActor.admin: AuditActor.admin,
    }[actor]
    diff: dict[str, Any] = {"verdict": verdict}
    if status_before is not None and status_before != event.status:
        diff["status"] = [status_before, event.status]
    if event.moderation_reason:
        diff["reason"] = event.moderation_reason
    await audit.record(
        session,
        action=f"event.moderation.{actor}",
        entity_type="event",
        entity_id=event.id,
        actor_type=audit_actor,
        actor_user_id=actor_user_id,
        diff=diff,
    )


async def reject_by_rules(
    session: AsyncSession, event: Event, violations: list[Violation], reason: str
) -> None:
    before = event.status
    event.status = EventStatus.rejected
    event.moderation_reason = reason
    await record_decision(
        session,
        event,
        actor=ModerationActor.rules,
        verdict=ModerationVerdict.reject,
        reasons=[{"code": v.code, "field": v.field, "message": v.message} for v in violations],
        status_before=before,
    )


# --- Правила подозрительности ---------------------------------------------------------


async def moderate_event(session: AsyncSession, event_id: int, *, notifier: Notifier) -> str | None:
    """Задача воркера после отправки. Возвращает статус или None, если решать нечего.

    Правила не публикуют: и official, и community ждут администратора (§6). Воркер считает
    признаки подозрительности, пишет их причиной для модератора и зовёт модераторов.
    """
    event = await session.get(Event, event_id, with_for_update=True)
    if event is None:
        return None
    if event.trust_tier == TrustTier.demo or event.status != EventStatus.pending:
        return None
    points, reasons = rules.score(
        rules.EventData(
            title=event.title or "",
            description=event.description,
            short_description=event.short_description,
        )
    )
    suspicious = points >= rules.SUSPICIOUS_SCORE
    event.moderation_reason = "; ".join(reasons) if suspicious else None
    await record_decision(
        session,
        event,
        actor=ModerationActor.rules,
        verdict=ModerationVerdict.review,
        confidence=None,
        reasons={"score": points, "reasons": reasons},
        status_before=event.status,
    )
    await session.commit()
    await notifier.alert_moderators("e", event.id)
    return str(event.status)


# --- Жалобы ----------------------------------------------------------------------------


async def report(
    session: AsyncSession, user: User, event_id: int, body: ReportIn, notifier: Notifier
) -> bool:
    event = await session.get(Event, event_id, with_for_update=True)
    if event is None or event.status not in (EventStatus.published, EventStatus.hidden):
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    inserted = await session.scalar(
        insert(Report)
        .values(event_id=event_id, user_id=user.id, reason=body.reason, comment=body.comment)
        .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
        .returning(Report.id)
    )
    if inserted is None:
        await session.rollback()
        return False
    await audit.record(
        session,
        action="event.report",
        entity_type="event",
        entity_id=event_id,
        actor_user_id=user.id,
        diff={"reason": body.reason},
    )
    open_reports = await session.scalar(
        select(func.count(func.distinct(Report.user_id))).where(
            Report.event_id == event_id, Report.resolved_at.is_(None)
        )
    )
    hidden_now = False
    if event.status == EventStatus.published and (open_reports or 0) >= REPORTS_TO_HIDE:
        event.status = EventStatus.hidden
        event.moderation_reason = texts.REPORTS_HIDDEN_REASON
        await record_decision(
            session,
            event,
            actor=ModerationActor.rules,
            verdict=ModerationVerdict.hide,
            reasons={"reports": open_reports},
            status_before=EventStatus.published,
        )
        hidden_now = True
    await session.commit()
    if hidden_now:
        await notify_owner(
            session,
            notifier,
            event,
            texts.EVENT_HIDDEN.format(title=event.title, reason=texts.REPORTS_HIDDEN_REASON),
        )
    return True


# --- Админ -----------------------------------------------------------------------------

_ADMIN_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "approve": (
        {EventStatus.pending, EventStatus.hidden, EventStatus.rejected},
        EventStatus.published,
    ),
    "reject": (
        {EventStatus.pending, EventStatus.hidden, EventStatus.published},
        EventStatus.rejected,
    ),
    "hide": ({EventStatus.pending, EventStatus.published}, EventStatus.hidden),
    # Вернуть на доработку: автор правит черновик и отправляет снова.
    "return": ({EventStatus.pending, EventStatus.hidden}, EventStatus.draft),
}


async def admin_decide(
    session: AsyncSession,
    admin_user: User,
    event_id: int,
    action: str,
    reason: str | None,
    notifier: Notifier,
    *,
    only_pending: bool = False,
) -> Event:
    """only_pending — кнопки из уведомления модератору: решают только ожидающую заявку,
    повторное нажатие (или после решения на сайте) даёт 409 already_decided с текущим статусом.
    """
    event = await session.get(Event, event_id, with_for_update=True)
    if event is None:
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    if only_pending and event.status != EventStatus.pending:
        raise AppError(
            "already_decided",
            "По заявке уже есть решение",
            status_code=409,
            details={"status": str(event.status)},
        )
    allowed, target = _ADMIN_TRANSITIONS[action]
    if event.status not in allowed:
        raise AppError(
            "bad_transition",
            f"Из статуса «{event.status}» это действие недоступно",
            status_code=409,
        )
    reason = reason.strip() if reason else None
    if action in ("reject", "return") and not reason:
        raise AppError("reason_required", "Укажи причину", status_code=422)
    before = event.status
    event.status = target
    event.moderation_reason = reason if action != "approve" else None
    if target == EventStatus.published and event.published_at is None:
        event.published_at = utcnow()
    await session.execute(
        update(Report)
        .where(Report.event_id == event.id, Report.resolved_at.is_(None))
        .values(resolved_at=utcnow())
    )
    await record_decision(
        session,
        event,
        actor=ModerationActor.admin,
        verdict={
            "approve": ModerationVerdict.approve,
            "reject": ModerationVerdict.reject,
            "hide": ModerationVerdict.hide,
            # Отдельного вердикта нет: возврат отличается статусом pending → draft в audit_log.
            "return": ModerationVerdict.reject,
        }[action],
        reasons=[reason] if reason else None,
        actor_user_id=admin_user.id,
        status_before=before,
    )
    await session.commit()
    text: str = {
        str(EventStatus.published): texts.EVENT_PUBLISHED.format(title=event.title),
        EventStatus.rejected: texts.EVENT_REJECTED.format(title=event.title, reason=reason),
        EventStatus.hidden: texts.EVENT_HIDDEN.format(
            title=event.title, reason=reason or texts.MODERATION_DEFAULT_REASON
        ),
        EventStatus.draft: texts.EVENT_RETURNED.format(title=event.title, reason=reason),
    }[target]
    await notify_owner(session, notifier, event, text)
    if before == EventStatus.pending:
        await notifier.moderation_closed("e", event.id)
    return event


async def admin_delete(
    session: AsyncSession,
    admin_user: User,
    event_id: int,
    reason: str | None,
    notifier: Notifier,
) -> None:
    """Администратор убирает афишу совсем (чистка): сеансы, «Пойду» и жалобы — каскадом.

    Права проверяет вызывающий (AdminDep, ADMIN_MAX_USER_IDS в боте), как у admin_decide.
    """
    event = await session.get(Event, event_id, with_for_update=True)
    if event is None:
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    reason = (reason or "").strip() or texts.MODERATION_DEFAULT_REASON
    title, before = event.title, event.status
    owners = await recipients(session, event)
    await audit.record(
        session,
        action="event.admin_delete",
        entity_type="event",
        entity_id=event.id,
        actor_type=AuditActor.admin,
        actor_user_id=admin_user.id,
        diff={
            "title": title,
            "status": str(before),
            "trust_tier": str(event.trust_tier),
            "reason": reason,
        },
    )
    await session.execute(delete(Event).where(Event.id == event.id))
    await session.commit()
    text = texts.EVENT_DELETED_BY_ADMIN.format(title=title, reason=reason)
    for user_id in owners:
        await notifier.send(user_id, text)
    if before == EventStatus.pending:
        await notifier.moderation_closed("e", event_id)


QueueFilter = Literal["new", "returned", "all"]


async def queue_events(
    session: AsyncSession, limit: int = 20, kind: QueueFilter = "all"
) -> list[QueueEvent]:
    """Очередь по времени подачи.

    returned — событие уже было у админа (отклонено или возвращено).
    """
    returned = (
        select(ModerationDecision.id)
        .where(
            ModerationDecision.entity_type == "event",
            ModerationDecision.entity_id == Event.id,
            ModerationDecision.actor_type == ModerationActor.admin,
        )
        .exists()
    )
    reports = (
        select(func.count())
        .where(Report.event_id == Event.id, Report.resolved_at.is_(None))
        .scalar_subquery()
    )
    next_start = (
        select(func.min(EventSession.starts_at))
        .where(EventSession.event_id == Event.id, EventSession.starts_at >= utcnow())
        .scalar_subquery()
    )
    stmt = (
        select(Event, Organization.name, reports, next_start, returned)
        .outerjoin(Organization, Organization.id == Event.organization_id)
        .where(Event.status.in_((EventStatus.pending, EventStatus.hidden)))
        .order_by(Event.updated_at, Event.id)
        .limit(limit)
    )
    if kind == "new":
        stmt = stmt.where(~returned)
    elif kind == "returned":
        stmt = stmt.where(returned)
    rows = await session.execute(stmt)
    return [
        QueueEvent(
            id=event.id,
            title=event.title,
            status=event.status,
            trust_tier=event.trust_tier,
            organization_id=event.organization_id,
            org_name=org_name,
            moderation_reason=event.moderation_reason,
            reports=count or 0,
            next_starts_at=starts,
            updated_at=event.updated_at,
            returned=bool(was_returned),
        )
        for event, org_name, count, starts, was_returned in rows.tuples()
    ]
