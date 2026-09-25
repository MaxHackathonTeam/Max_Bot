"""Модерация событий (§6): решения правил, LLM и админа, жалобы, очередь.

Каждое решение пишется в moderation_decisions и audit_log.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.core.errors import AppError
from app.core.jobs import MODERATE_EVENT, JobQueue
from app.llm.runner import LlmRunner
from app.llm.schemas import ModerationVerdictOut
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
from app.models.geo import Locality, Venue
from app.models.orgs import Organization, OrgMember
from app.models.system import ModerationDecision
from app.models.users import User
from app.moderation.rules import Violation
from app.schemas.manage import QueueEvent, ReportIn
from app.services import audit
from app.services.categories import BY_SLUG, CATEGORIES
from app.services.events import utcnow
from app.services.notify import Notifier

log = structlog.get_logger(__name__)

COMMUNITY_CONFIDENCE_MIN = 0.8
REPORTS_TO_HIDE = 3
# Повтор LLM-модерации при недоступности GigaChat: 5, 10, 20… мин, всего не дольше 6 ч.
RETRY_BASE_S = 300
RETRY_TOTAL = timedelta(hours=6)


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
    for user_id in await recipients(session, event):
        await notifier.send(user_id, text, f"ev_{event.id}")


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
        ModerationActor.llm: AuditActor.llm,
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


# --- LLM ------------------------------------------------------------------------------


async def _prompt_vars(session: AsyncSession, event: Event) -> dict[str, object]:
    place = None
    if event.venue_id is not None:
        venue = await session.get(Venue, event.venue_id)
        if venue is not None:
            place = ", ".join(p for p in (venue.name, venue.address) if p)
    if place is None and event.locality_id is not None:
        place = await session.scalar(select(Locality.name).where(Locality.id == event.locality_id))
    if event.is_online:
        place = f"{place}; онлайн" if place else "онлайн"
    price = event.price_type
    if event.price_min is not None or event.price_max is not None:
        price = f"{price}: {event.price_min or ''}–{event.price_max or ''} ₽"
    category = BY_SLUG.get(event.category or "")
    return {
        "title": event.title,
        "category": category.name if category else event.category,
        "description": "\n".join(p for p in (event.short_description, event.description) if p),
        "place": place,
        "price": price,
        "links": ", ".join(u for u in (event.ticket_url, event.online_url) if u),
        "categories": ", ".join(c.slug for c in CATEGORIES),
    }


def llm_reason(value: ModerationVerdictOut | None) -> str:
    if value is None:
        return texts.MODERATION_DEFAULT_REASON
    parts = [texts.MODERATION_CATEGORY_REASONS[c] for c in value.categories]
    if not parts and value.reasons:
        parts = value.reasons[:2]
    return "; ".join(dict.fromkeys(parts)) or texts.MODERATION_DEFAULT_REASON


def decide_llm(tier: str, verdict: ModerationVerdictOut | None) -> str:
    """Статус по §6 п. 3. verdict=None — невалидный ответ, то же, что review."""
    kind = verdict.verdict if verdict is not None else "review"
    confidence = verdict.confidence if verdict is not None else 0.0
    if tier == TrustTier.official:
        return EventStatus.published if kind == "approve" else EventStatus.hidden
    if kind == "approve" and confidence >= COMMUNITY_CONFIDENCE_MIN:
        return EventStatus.published
    if kind == "reject" and confidence >= COMMUNITY_CONFIDENCE_MIN:
        return EventStatus.rejected
    return EventStatus.pending


def retry_delay(attempt: int) -> float | None:
    """Задержка перед попыткой attempt+1 или None, если 6 часов исчерпаны."""
    total = sum(RETRY_BASE_S * 2**i for i in range(attempt + 1))
    if total > RETRY_TOTAL.total_seconds():
        return None
    return float(RETRY_BASE_S * 2**attempt)


async def moderate_event(
    session: AsyncSession,
    event_id: int,
    *,
    llm: LlmRunner,
    notifier: Notifier,
    jobs: JobQueue,
    attempt: int = 0,
) -> str | None:
    """Задача воркера. Возвращает новый статус или None, если модерировать нечего."""
    event = await session.get(Event, event_id)
    if event is None:
        return None
    tier = event.trust_tier
    expected = EventStatus.published if tier == TrustTier.official else EventStatus.pending
    if tier == TrustTier.demo or event.status != expected:
        return None
    variables = await _prompt_vars(session, event)
    version = event.updated_at
    # Блокировку строки не держим, пока ждём LLM: автор может править событие.
    await session.commit()

    result = await llm.run_json("moderation", "moderation", ModerationVerdictOut, **variables)
    if result.status == "unavailable":
        if tier == TrustTier.community:
            delay = retry_delay(attempt)
            if delay is not None:
                await jobs.enqueue(
                    MODERATE_EVENT,
                    event_id,
                    attempt + 1,
                    defer_s=delay,
                    job_id=f"moderate:{event_id}:{attempt + 1}",
                )
            else:
                log.warning("moderation_llm_gave_up", event_id=event_id)
        # official остаётся опубликованным по одним правилам (§6 п. 3).
        return str(expected)

    await session.refresh(event, with_for_update=True)
    if event.status != expected or event.updated_at != version:
        # Событие изменили во время проверки — решение примет следующая задача.
        await session.rollback()
        return None
    value = result.value
    new_status = decide_llm(event.trust_tier, value)
    before = event.status
    reason = llm_reason(value) if new_status in (EventStatus.rejected, EventStatus.hidden) else None
    event.status = new_status
    if reason is not None:
        event.moderation_reason = reason
    if new_status == EventStatus.published and event.published_at is None:
        event.published_at = utcnow()
    verdict = ModerationVerdict(value.verdict) if value is not None else ModerationVerdict.review
    await record_decision(
        session,
        event,
        actor=ModerationActor.llm,
        verdict=verdict,
        confidence=value.confidence if value is not None else None,
        reasons=(
            {
                "categories": value.categories,
                "reasons": value.reasons,
                "fixed_category": value.fixed_category,
            }
            if value is not None
            else {"invalid": True}
        ),
        model=result.model,
        prompt_version=result.prompt_version,
        status_before=before,
    )
    await session.commit()

    if before != new_status:
        text = {
            str(EventStatus.published): texts.EVENT_PUBLISHED.format(title=event.title),
            EventStatus.rejected: texts.EVENT_REJECTED.format(title=event.title, reason=reason),
            EventStatus.hidden: texts.EVENT_HIDDEN.format(title=event.title, reason=reason),
        }.get(new_status)
        if text is not None:
            await notify_owner(session, notifier, event, text)
    return new_status


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
}


async def admin_decide(
    session: AsyncSession,
    admin_user: User,
    event_id: int,
    action: str,
    reason: str | None,
    notifier: Notifier,
) -> Event:
    event = await session.get(Event, event_id, with_for_update=True)
    if event is None:
        raise AppError("event_not_found", "Событие не найдено", status_code=404)
    allowed, target = _ADMIN_TRANSITIONS[action]
    if event.status not in allowed:
        raise AppError(
            "bad_transition",
            f"Из статуса «{event.status}» это действие недоступно",
            status_code=409,
        )
    reason = reason.strip() if reason else None
    if action == "reject" and not reason:
        raise AppError("reason_required", "Укажи причину отказа", status_code=422)
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
    }[target]
    await notify_owner(session, notifier, event, text)
    return event


async def queue_events(session: AsyncSession, limit: int = 20) -> list[QueueEvent]:
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
    rows = await session.execute(
        select(Event, Organization.name, reports, next_start)
        .outerjoin(Organization, Organization.id == Event.organization_id)
        .where(Event.status.in_((EventStatus.pending, EventStatus.hidden)))
        .order_by(Event.updated_at, Event.id)
        .limit(limit)
    )
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
        )
        for event, org_name, count, starts in rows.tuples()
    ]
