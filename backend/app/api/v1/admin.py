"""Раздел модератора: очередь, решения, отзыв верификации, аудит (§6, FR-ADM)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import AdminDep, NotifierDep, SessionDep
from app.schemas.manage import (
    AuditPage,
    EventDecisionIn,
    QueueOut,
    RevokeIn,
    RevokeOut,
    VerificationDecisionIn,
)
from app.schemas.orgs import VerificationOut
from app.services import admin as admin_service
from app.services import moderation as moderation_service
from app.services import orgs as orgs_service
from app.services import verification as verification_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/queue", response_model=QueueOut, summary="Очередь модерации")
async def queue(
    _admin: AdminDep,
    session: SessionDep,
    kind: Annotated[Literal["new", "returned", "all"], Query(alias="filter")] = "all",
) -> QueueOut:
    return await admin_service.queue(session, kind=kind)


@router.post("/events/{event_id}/decision", status_code=204, summary="Решение по событию")
async def decide_event(
    event_id: int,
    body: EventDecisionIn,
    admin: AdminDep,
    session: SessionDep,
    notifier: NotifierDep,
) -> None:
    await moderation_service.admin_decide(
        session, admin.user, event_id, body.action, body.reason, notifier
    )


@router.post(
    "/verifications/{request_id}/decision",
    response_model=VerificationOut,
    summary="Решение по заявке на проверку",
)
async def decide_verification(
    request_id: int,
    body: VerificationDecisionIn,
    admin: AdminDep,
    session: SessionDep,
    notifier: NotifierDep,
) -> VerificationOut:
    request = await verification_service.decide(
        session, admin.user, request_id, body.action == "approve", body.reason, notifier
    )
    return verification_service.to_out(request)


@router.post("/orgs/{org_id}/revoke", response_model=RevokeOut, summary="Отозвать верификацию")
async def revoke(org_id: int, body: RevokeIn, admin: AdminDep, session: SessionDep) -> RevokeOut:
    moved = await orgs_service.revoke(session, admin.user, org_id, body.reason)
    return RevokeOut(org_id=org_id, events_moved=moved)


@router.get("/audit", response_model=AuditPage, summary="Журнал аудита")
async def audit(
    _admin: AdminDep,
    session: SessionDep,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    entity_id: int | None = None,
    before_id: int | None = None,
) -> AuditPage:
    return await admin_service.audit_page(
        session, entity_type=entity_type, entity_id=entity_id, before_id=before_id
    )
