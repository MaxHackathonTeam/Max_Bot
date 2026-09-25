"""Организации, команда и приглашения (§5, §5.4). Права проверяются здесь, не в роутерах."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.dadata.party import PartyRegistry
from app.models.enums import (
    AuditActor,
    ConsentDoc,
    OrgRole,
    TrustTier,
    VerificationMethod,
    VerificationStatus,
)
from app.models.events import Event
from app.models.geo import Locality
from app.models.orgs import Organization, OrgInvite, OrgMember
from app.models.users import User
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
)
from app.services import audit
from app.services import users as users_service
from app.services.events import utcnow

log = structlog.get_logger(__name__)

INVITE_TTL = timedelta(hours=24)
INVITE_PREFIX = "inv_"
MAX_ORGS_PER_USER = 10

_ORG_FIELDS = (
    "name",
    "kind",
    "inn",
    "locality_id",
    "address",
    "website",
    "vk_url",
    "phone",
    "email",
    "description",
)
# Смена этих полей у проверенной организации требует повторной верификации.
_IDENTITY_FIELDS = frozenset({"inn"})


@dataclass(frozen=True)
class Access:
    org: Organization
    role: OrgRole | None
    is_admin: bool

    @property
    def is_member(self) -> bool:
        return self.role is not None

    @property
    def is_owner(self) -> bool:
        return self.role == OrgRole.owner


def is_verified(org: Organization) -> bool:
    return org.verification_status == VerificationStatus.verified


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_url(bot_username: str, token: str) -> str | None:
    if not bot_username:
        return None
    return f"https://max.ru/{bot_username}?startapp={INVITE_PREFIX}{token}"


def display_name(user: User) -> str:
    parts = [p for p in (user.first_name, user.last_name) if p]
    return " ".join(parts) or (f"@{user.username}" if user.username else f"Пользователь {user.id}")


def _snapshot(org: Organization) -> dict[str, Any]:
    return {f: getattr(org, f) for f in _ORG_FIELDS}


async def get_role(session: AsyncSession, org_id: int, user_id: int) -> OrgRole | None:
    role = await session.scalar(
        select(OrgMember.role).where(OrgMember.org_id == org_id, OrgMember.user_id == user_id)
    )
    return OrgRole(role) if role is not None else None


async def get_access(
    session: AsyncSession, org_id: int, user: User | None, *, admin: bool = False
) -> Access:
    org = await session.get(Organization, org_id)
    if org is None:
        raise AppError("org_not_found", "Организация не найдена", status_code=404)
    role = await get_role(session, org_id, user.id) if user is not None else None
    return Access(org=org, role=role, is_admin=admin)


async def require_member(
    session: AsyncSession, org_id: int, user: User, *, admin: bool = False
) -> Access:
    access = await get_access(session, org_id, user, admin=admin)
    if not access.is_member and not admin:
        # Не раскрываем чужие закрытые данные: для постороннего это «нет доступа».
        raise AppError("forbidden", "Ты не состоишь в этой организации", status_code=403)
    return access


async def require_owner(
    session: AsyncSession, org_id: int, user: User, *, admin: bool = False
) -> Access:
    access = await get_access(session, org_id, user, admin=admin)
    if not access.is_owner and not admin:
        raise AppError("forbidden", "Это может сделать только владелец организации", 403)
    return access


async def _require_org_consent(session: AsyncSession, user: User) -> None:
    accepted = await users_service._accepted(session, user.id)
    version = users_service.CONSENT_VERSIONS[ConsentDoc.org_pd]
    if (ConsentDoc.org_pd.value, version) not in accepted:
        raise AppError(
            "consent_required",
            "Прими согласие на обработку данных организации",
            status_code=403,
            details={"doc": ConsentDoc.org_pd.value, "version": version},
        )


async def _check_locality(session: AsyncSession, locality_id: int | None) -> None:
    if locality_id is not None and await session.get(Locality, locality_id) is None:
        raise AppError("locality_not_found", "Населённый пункт не найден", status_code=422)


async def to_out(session: AsyncSession, org: Organization, role: OrgRole | None) -> OrgOut:
    locality_name = None
    if org.locality_id is not None:
        locality_name = await session.scalar(
            select(Locality.name).where(Locality.id == org.locality_id)
        )
    return OrgOut(
        id=org.id,
        name=org.name,
        kind=org.kind,
        inn=org.inn,
        ogrn=org.ogrn,
        registry_name=org.registry_name,
        locality_id=org.locality_id,
        locality_name=locality_name,
        address=org.address,
        website=org.website,
        vk_url=org.vk_url,
        description=org.description,
        phone=org.phone if role is not None else None,
        email=org.email if role is not None else None,
        verified=is_verified(org),
        verification_status=org.verification_status,
        verification_method=org.verification_method,
        verified_at=org.verified_at,
        my_role=role,
    )


async def create(session: AsyncSession, user: User, body: OrgCreate) -> Organization:
    await _require_org_consent(session, user)
    await _check_locality(session, body.locality_id)
    owned = await session.scalar(
        select(func.count()).select_from(OrgMember).where(OrgMember.user_id == user.id)
    )
    if (owned or 0) >= MAX_ORGS_PER_USER:
        raise AppError("limit_exceeded", "Слишком много организаций на одного человека", 429)
    org = Organization(**body.model_dump(), created_by=user.id)
    session.add(org)
    await session.flush()
    session.add(OrgMember(org_id=org.id, user_id=user.id, role=OrgRole.owner))
    await audit.record(
        session,
        action="org.create",
        entity_type="organization",
        entity_id=org.id,
        actor_user_id=user.id,
        diff=audit.changes({}, _snapshot(org)),
    )
    await session.commit()
    return org


async def list_mine(session: AsyncSession, user: User) -> list[tuple[Organization, OrgRole]]:
    rows = await session.execute(
        select(Organization, OrgMember.role)
        .join(OrgMember, OrgMember.org_id == Organization.id)
        .where(OrgMember.user_id == user.id)
        .order_by(Organization.name, Organization.id)
    )
    return [(org, OrgRole(role)) for org, role in rows.tuples()]


async def patch(
    session: AsyncSession, user: User, org_id: int, body: OrgUpdate, *, admin: bool = False
) -> Access:
    access = await require_owner(session, org_id, user, admin=admin)
    org = access.org
    data = body.model_dump(exclude_unset=True)
    if any(key in data and data[key] is None for key in ("name", "kind")):
        raise AppError("bad_request", "Название и тип организации обязательны", status_code=422)
    if "locality_id" in data:
        await _check_locality(session, data["locality_id"])
    before = _snapshot(org)
    for key, value in data.items():
        setattr(org, key, value)
    diff = audit.changes(before, _snapshot(org))
    if not diff:
        return access
    if is_verified(org) and _IDENTITY_FIELDS & diff.keys():
        raise AppError(
            "verified_identity_locked",
            "ИНН проверенной организации менять нельзя — напиши администратору",
            status_code=409,
        )
    await audit.record(
        session,
        action="org.update",
        entity_type="organization",
        entity_id=org.id,
        actor_type=AuditActor.admin if admin and not access.is_owner else AuditActor.user,
        actor_user_id=user.id,
        diff=diff,
    )
    await session.commit()
    return access


async def lookup(registry: PartyRegistry | None, inn: str) -> RegistryLookupOut:
    if registry is None:
        raise AppError("registry_unavailable", "Реестр сейчас недоступен, заполни вручную", 503)
    try:
        party = await registry.find_by_inn(inn)
    except Exception as exc:
        log.warning("registry_lookup_failed", error=type(exc).__name__)
        raise AppError(
            "registry_unavailable", "Реестр сейчас недоступен, заполни вручную", 503
        ) from exc
    if party is None:
        return RegistryLookupOut(found=False, inn=inn)
    return RegistryLookupOut(
        found=True,
        inn=party.inn,
        ogrn=party.ogrn,
        name=party.display_name,
        status=party.status,
        address=party.address,
        region=party.region,
        kind="individual" if party.kind == "INDIVIDUAL" else "legal",
    )


# --- Команда ---------------------------------------------------------------------------


async def members(session: AsyncSession, user: User, org_id: int) -> list[MemberOut]:
    await require_member(session, org_id, user)
    rows = await session.execute(
        select(OrgMember, User)
        .join(User, User.id == OrgMember.user_id)
        .where(OrgMember.org_id == org_id)
        .order_by(OrgMember.created_at, OrgMember.id)
    )
    return [
        MemberOut(
            user_id=u.id,
            name=display_name(u),
            role=OrgRole(m.role),
            joined_at=m.created_at,
            is_me=u.id == user.id,
        )
        for m, u in rows.tuples()
    ]


async def remove_member(session: AsyncSession, user: User, org_id: int, member_id: int) -> None:
    """Владелец удаляет кого угодно, участник — только себя. Последнего владельца — нельзя."""
    access = await require_member(session, org_id, user)
    if member_id != user.id and not access.is_owner:
        raise AppError("forbidden", "Это может сделать только владелец организации", 403)
    member = await session.scalar(
        select(OrgMember)
        .where(OrgMember.org_id == org_id, OrgMember.user_id == member_id)
        .with_for_update()
    )
    if member is None:
        raise AppError("member_not_found", "Участник не найден", status_code=404)
    if member.role == OrgRole.owner:
        owners = await session.scalar(
            select(func.count())
            .select_from(OrgMember)
            .where(OrgMember.org_id == org_id, OrgMember.role == OrgRole.owner)
        )
        if (owners or 0) <= 1:
            raise AppError("last_owner", "Нельзя удалить последнего владельца", status_code=409)
    await session.delete(member)
    await audit.record(
        session,
        action="org.member_remove",
        entity_type="organization",
        entity_id=org_id,
        actor_user_id=user.id,
        diff={"user_id": member_id, "role": member.role},
    )
    await session.commit()


async def create_invite(
    session: AsyncSession,
    user: User,
    org_id: int,
    body: InviteCreate,
    settings: Settings,
    *,
    admin: bool = False,
) -> InviteOut:
    if body.grants_verification and not admin:
        raise AppError("forbidden", "Приглашение с верификацией выдаёт только администратор", 403)
    await require_owner(session, org_id, user, admin=admin)
    token = secrets.token_urlsafe(24)
    invite = OrgInvite(
        org_id=org_id,
        token_hash=hash_token(token),
        role=body.role,
        grants_verification=body.grants_verification,
        expires_at=utcnow() + INVITE_TTL,
        created_by=user.id,
    )
    session.add(invite)
    await session.flush()
    await audit.record(
        session,
        action="org.invite_create",
        entity_type="organization",
        entity_id=org_id,
        actor_type=AuditActor.admin if body.grants_verification else AuditActor.user,
        actor_user_id=user.id,
        diff={
            "invite_id": invite.id,
            "role": body.role,
            "grants_verification": body.grants_verification,
        },
    )
    await session.commit()
    return InviteOut(
        token=token,
        payload=f"{INVITE_PREFIX}{token}",
        url=invite_url(settings.max_bot_username, token),
        role=body.role,
        grants_verification=body.grants_verification,
        expires_at=invite.expires_at,
    )


def _invite_problem(invite: OrgInvite, now: datetime) -> str | None:
    if invite.used_at is not None:
        return "Приглашение уже использовано"
    if invite.expires_at <= now:
        return "Срок приглашения истёк — попроси новое"
    return None


async def preview_invite(session: AsyncSession, token: str) -> InvitePreview:
    row = (
        await session.execute(
            select(OrgInvite, Organization.name)
            .join(Organization, Organization.id == OrgInvite.org_id)
            .where(OrgInvite.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise AppError("invite_not_found", "Приглашение не найдено", status_code=404)
    invite, org_name = row
    problem = _invite_problem(invite, utcnow())
    return InvitePreview(
        org_id=invite.org_id,
        org_name=org_name,
        role=OrgRole(invite.role),
        grants_verification=invite.grants_verification,
        expires_at=invite.expires_at,
        valid=problem is None,
        reason=problem,
    )


async def mark_verified(
    session: AsyncSession,
    org: Organization,
    method: VerificationMethod,
    *,
    actor_type: AuditActor,
    actor_user_id: int | None,
) -> None:
    before = {"verification_status": org.verification_status}
    org.verification_status = VerificationStatus.verified
    org.verification_method = method
    org.verified_at = utcnow()
    org.verified_by_user_id = actor_user_id
    await audit.record(
        session,
        action="org.verify",
        entity_type="organization",
        entity_id=org.id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        diff={
            **audit.changes(before, {"verification_status": org.verification_status}),
            "method": method,
        },
    )


async def accept_invite(session: AsyncSession, user: User, token: str) -> InviteAccepted:
    await _require_org_consent(session, user)
    invite = await session.scalar(
        select(OrgInvite).where(OrgInvite.token_hash == hash_token(token)).with_for_update()
    )
    if invite is None:
        raise AppError("invite_not_found", "Приглашение не найдено", status_code=404)
    problem = _invite_problem(invite, utcnow())
    if problem is not None:
        raise AppError("invite_invalid", problem, status_code=410)
    org = await session.get(Organization, invite.org_id, with_for_update=True)
    if org is None:
        raise AppError("org_not_found", "Организация не найдена", status_code=404)

    member = await session.scalar(
        select(OrgMember).where(OrgMember.org_id == org.id, OrgMember.user_id == user.id)
    )
    if member is None:
        member = OrgMember(
            org_id=org.id, user_id=user.id, role=invite.role, invited_by=invite.created_by
        )
        session.add(member)
    elif member.role != OrgRole.owner and invite.role == OrgRole.owner:
        member.role = OrgRole.owner
    invite.used_by = user.id
    invite.used_at = utcnow()
    await audit.record(
        session,
        action="org.invite_accept",
        entity_type="organization",
        entity_id=org.id,
        actor_user_id=user.id,
        diff={"invite_id": invite.id, "role": member.role},
    )
    if invite.grants_verification and not is_verified(org):
        # Способ A: доверие переносится от администратора, выдавшего ссылку.
        await mark_verified(
            session,
            org,
            VerificationMethod.invite,
            actor_type=AuditActor.admin,
            actor_user_id=invite.created_by,
        )
    await session.commit()
    return InviteAccepted(org_id=org.id, role=OrgRole(member.role), verified=is_verified(org))


async def revoke(session: AsyncSession, admin_user: User, org_id: int, reason: str | None) -> int:
    """Отзыв верификации (§5.3): официальные события организации переходят в `community`."""
    org = await session.get(Organization, org_id, with_for_update=True)
    if org is None:
        raise AppError("org_not_found", "Организация не найдена", status_code=404)
    if org.verification_status != VerificationStatus.verified:
        raise AppError("not_verified", "Организация не проверена", status_code=409)
    org.verification_status = VerificationStatus.revoked
    org.verification_method = None
    org.verified_at = None
    moved = list(
        await session.scalars(
            update(Event)
            .where(Event.organization_id == org.id, Event.trust_tier == TrustTier.official)
            .values(trust_tier=TrustTier.community, pushkin_card=False)
            .returning(Event.id)
        )
    )
    await audit.record(
        session,
        action="org.revoke",
        entity_type="organization",
        entity_id=org.id,
        actor_type=AuditActor.admin,
        actor_user_id=admin_user.id,
        diff={
            "verification_status": [VerificationStatus.verified, VerificationStatus.revoked],
            "reason": reason,
            "events_to_community": moved,
        },
    )
    await session.commit()
    return len(moved)


async def owner_ids(session: AsyncSession, org_id: int) -> list[int]:
    return list(
        await session.scalars(
            select(OrgMember.user_id).where(
                OrgMember.org_id == org_id, OrgMember.role == OrgRole.owner
            )
        )
    )
