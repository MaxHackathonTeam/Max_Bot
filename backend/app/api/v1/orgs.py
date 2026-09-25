"""Организации, команда, приглашения и верификация (FR-ORG)."""

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import (
    AuthDep,
    JobsDep,
    NotifierDep,
    RegistryDep,
    SessionDep,
    SettingsDep,
    is_admin,
)
from app.core.jobs import REQUEST_PHONE
from app.models.enums import EventStatus, OrgRole, VerificationMethod
from app.schemas.manage import MyEventItem
from app.schemas.orgs import (
    InviteAccepted,
    InviteCreate,
    InviteOut,
    InvitePreview,
    MemberOut,
    OrgCreate,
    OrgOut,
    OrgUpdate,
    RegistryLookupOut,
    VerificationOut,
    VerificationStart,
)
from app.services import analytics, event_editor
from app.services import orgs as orgs_service
from app.services import verification as verification_service

router = APIRouter(prefix="/orgs", tags=["orgs"])
invites_router = APIRouter(prefix="/invites", tags=["orgs"])


@router.post("", response_model=OrgOut, status_code=201, summary="Создать организацию")
async def create_org(body: OrgCreate, auth: AuthDep, session: SessionDep) -> OrgOut:
    org = await orgs_service.create(session, auth.user, body)
    return await orgs_service.to_out(session, org, await _role(session, org.id, auth))


@router.get("/mine", response_model=list[OrgOut], summary="Мои организации")
async def my_orgs(auth: AuthDep, session: SessionDep) -> list[OrgOut]:
    return [
        await orgs_service.to_out(session, org, role)
        for org, role in await orgs_service.list_mine(session, auth.user)
    ]


@router.get("/lookup", response_model=RegistryLookupOut, summary="Найти организацию по ИНН")
async def lookup(inn: str, _auth: AuthDep, registry: RegistryDep) -> RegistryLookupOut:
    return await orgs_service.lookup(registry, inn)


@router.get("/{org_id}", response_model=OrgOut, summary="Организация")
async def get_org(org_id: int, auth: AuthDep, session: SessionDep) -> OrgOut:
    access = await orgs_service.get_access(session, org_id, auth.user)
    return await orgs_service.to_out(session, access.org, access.role)


@router.patch("/{org_id}", response_model=OrgOut, summary="Изменить организацию")
async def patch_org(
    org_id: int, body: OrgUpdate, auth: AuthDep, session: SessionDep, settings: SettingsDep
) -> OrgOut:
    access = await orgs_service.patch(
        session, auth.user, org_id, body, admin=is_admin(auth, settings)
    )
    return await orgs_service.to_out(session, access.org, access.role)


@router.get("/{org_id}/events", response_model=list[MyEventItem], summary="События организации")
async def org_events(
    org_id: int, auth: AuthDep, session: SessionDep, status: EventStatus | None = None
) -> list[MyEventItem]:
    return await event_editor.org_events(session, auth.user, org_id, status)


@router.get("/{org_id}/stats", summary="Статистика организации")
async def stats(org_id: int, auth: AuthDep, session: SessionDep) -> dict[str, Any]:
    return await analytics.organization_stats(session, auth.user, org_id)


@router.get("/{org_id}/members", response_model=list[MemberOut], summary="Команда")
async def members(org_id: int, auth: AuthDep, session: SessionDep) -> list[MemberOut]:
    return await orgs_service.members(session, auth.user, org_id)


@router.delete("/{org_id}/members/{user_id}", status_code=204, summary="Убрать из команды")
async def remove_member(org_id: int, user_id: int, auth: AuthDep, session: SessionDep) -> Response:
    await orgs_service.remove_member(session, auth.user, org_id, user_id)
    return Response(status_code=204)


@router.post(
    "/{org_id}/invites", response_model=InviteOut, status_code=201, summary="Пригласить в команду"
)
async def create_invite(
    org_id: int, body: InviteCreate, auth: AuthDep, session: SessionDep, settings: SettingsDep
) -> InviteOut:
    return await orgs_service.create_invite(
        session, auth.user, org_id, body, settings, admin=is_admin(auth, settings)
    )


@router.get(
    "/{org_id}/verification", response_model=VerificationOut | None, summary="Статус проверки"
)
async def get_verification(
    org_id: int, auth: AuthDep, session: SessionDep, settings: SettingsDep
) -> VerificationOut | None:
    request = await verification_service.get_for_owner(
        session, auth.user, org_id, admin=is_admin(auth, settings)
    )
    return verification_service.to_out(request) if request is not None else None


@router.post(
    "/{org_id}/verification",
    response_model=VerificationOut,
    status_code=201,
    summary="Подать заявку на проверку",
)
async def start_verification(
    org_id: int,
    body: VerificationStart,
    auth: AuthDep,
    session: SessionDep,
    registry: RegistryDep,
    notifier: NotifierDep,
    jobs: JobsDep,
) -> VerificationOut:
    request = await verification_service.start(
        session, auth.user, org_id, body, registry=registry, notifier=notifier
    )
    if request.method == VerificationMethod.registry_auto and not request.phone_verified:
        await jobs.enqueue(REQUEST_PHONE, auth.user.id, org_id)
    return verification_service.to_out(request)


@router.post(
    "/{org_id}/verification/recheck",
    response_model=VerificationOut,
    status_code=202,
    summary="Проверить сайт ещё раз",
)
async def recheck_verification(
    org_id: int, auth: AuthDep, session: SessionDep, jobs: JobsDep
) -> VerificationOut:
    request = await verification_service.recheck(session, auth.user, org_id, jobs)
    return verification_service.to_out(request)


@invites_router.get("/{token}", response_model=InvitePreview, summary="Приглашение")
async def preview_invite(token: str, _auth: AuthDep, session: SessionDep) -> InvitePreview:
    return await orgs_service.preview_invite(session, token)


@invites_router.post("/{token}/accept", response_model=InviteAccepted, summary="Вступить")
async def accept_invite(token: str, auth: AuthDep, session: SessionDep) -> InviteAccepted:
    return await orgs_service.accept_invite(session, auth.user, token)


async def _role(session: SessionDep, org_id: int, auth: AuthDep) -> OrgRole | None:
    return await orgs_service.get_role(session, org_id, auth.user.id)
