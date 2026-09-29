"""Верификация организации (§5.3): B — ИНН, телефон, код на сайте; C — админ.

Способ A (приглашение) — в services.orgs.accept_invite. Внешних реестров нет: ИНН проверяется
локально (формат и контрольная сумма), принадлежность сайта — кодом на странице.
"""

import base64
import hashlib
import hmac
import secrets
import string
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.core.errors import AppError
from app.core.jobs import CHECK_VERIFICATION, JobQueue
from app.integrations.safe_fetch import FetchedPage, FetchError, UnsafeUrlError, fetch_page
from app.models.enums import AuditActor, VerificationMethod, VerificationStatus
from app.models.orgs import Organization, VerificationRequest
from app.models.users import User
from app.schemas.orgs import VerificationOut, VerificationStart, VerificationStep
from app.services import audit
from app.services import orgs as orgs_service
from app.services.events import utcnow
from app.services.notify import Notifier

log = structlog.get_logger(__name__)

RETRY_INTERVAL = timedelta(minutes=10)
CODE_PREFIX = "AFISHA-"
_CODE_ALPHABET = string.ascii_uppercase + string.digits

Fetch = Callable[[str], Awaitable[FetchedPage]]


def new_code() -> str:
    return CODE_PREFIX + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


# --- Шаг 1: ИНН ------------------------------------------------------------------------

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _control(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(d * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def inn_valid(inn: str) -> bool:
    """Контрольные цифры ИНН: 10 знаков — юрлицо, 12 — ИП и физлицо."""
    if not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(c) for c in inn]
    if len(d) == 10:
        return _control(d, _INN10_WEIGHTS) == d[9]
    return _control(d, _INN12_WEIGHTS_1) == d[10] and _control(d, _INN12_WEIGHTS_2) == d[11]


def _bad_inn() -> AppError:
    return AppError(
        "validation_error",
        "ИНН с ошибкой: не сходится контрольная цифра",
        status_code=422,
        details={"field": "inn"},
    )


def check_inn(inn: str) -> dict[str, Any]:
    """Снимок для registry_snapshot: {ok, message, at, inn, type}."""
    ok = inn_valid(inn)
    return {
        "ok": ok,
        "at": utcnow().isoformat(),
        "inn": inn,
        "type": "LEGAL" if len(inn) == 10 else "INDIVIDUAL",
        "message": "ИНН корректен" if ok else f"ИНН {inn} с ошибкой: не сходится контрольная цифра",
    }


# --- Шаг 2: телефон (request_contact) ----------------------------------------------------


def contact_hash_valid(vcf_info: str, received: str, bot_token: str) -> bool:
    """HMAC-SHA256(ключ — токен бота, сообщение — vcf_info) по §5.3.

    В api-schema MAX алгоритм и кодировка `hash` не описаны: принимаем hex и base64,
    проверка на живом устройстве — в docs/HUMAN_TODO.md.
    """
    if not vcf_info or not received or not bot_token:
        return False
    digest = hmac.new(bot_token.encode(), vcf_info.encode(), hashlib.sha256).digest()
    variants = {
        digest.hex(),
        base64.b64encode(digest).decode(),
        base64.urlsafe_b64encode(digest).decode(),
        base64.b64encode(digest).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    }
    candidate = received.strip()
    return any(
        hmac.compare_digest(candidate.lower() if len(v) == 64 else candidate, v) for v in variants
    )


PhoneResult = Literal["ok", "no_request", "bad_signature", "not_own"]


@dataclass(frozen=True)
class ContactData:
    vcf_info: str | None
    hash: str | None
    max_user_id: int | None


async def confirm_phone(
    session: AsyncSession,
    user: User,
    contact: ContactData,
    bot_token: str,
    notifier: Notifier,
) -> PhoneResult:
    if contact.max_user_id is not None and contact.max_user_id != user.max_user_id:
        return "not_own"
    if not contact_hash_valid(contact.vcf_info or "", contact.hash or "", bot_token):
        log.info("contact_hash_invalid", user_id=user.id)
        return "bad_signature"
    requests = list(
        await session.scalars(
            select(VerificationRequest)
            .where(
                VerificationRequest.submitted_by == user.id,
                VerificationRequest.method == VerificationMethod.registry_auto,
                VerificationRequest.status == VerificationStatus.pending,
            )
            .with_for_update()
        )
    )
    if not requests:
        return "no_request"
    finalized: list[tuple[VerificationRequest, Organization]] = []
    for request in requests:
        if not request.phone_verified:
            request.phone_verified = True
            await audit.record(
                session,
                action="verification.phone",
                entity_type="verification_request",
                entity_id=request.id,
                actor_user_id=user.id,
                diff={"phone_verified": [False, True]},
            )
        org = await session.get(Organization, request.org_id)
        if org is not None and await try_finalize(session, request, org):
            finalized.append((request, org))
    await session.commit()
    for request, org in finalized:
        await _notify_done(notifier, request, org)
    return "ok"


# --- Шаг 3: код на сайте -----------------------------------------------------------


def _all_ok(request: VerificationRequest) -> bool:
    return bool(
        (request.registry_snapshot or {}).get("ok")
        and request.phone_verified
        and (request.site_check or {}).get("ok")
    )


async def try_finalize(
    session: AsyncSession, request: VerificationRequest, org: Organization
) -> bool:
    """Все шаги B пройдены → verified. Возвращает True, если статус изменился сейчас."""
    if request.status != VerificationStatus.pending or not _all_ok(request):
        return False
    request.status = VerificationStatus.verified
    request.decided_at = utcnow()
    await audit.record(
        session,
        action="verification.verified",
        entity_type="verification_request",
        entity_id=request.id,
        actor_type=AuditActor.system,
        diff={"status": [VerificationStatus.pending, VerificationStatus.verified]},
    )
    if not orgs_service.is_verified(org):
        await orgs_service.mark_verified(
            session,
            org,
            VerificationMethod.registry_auto,
            actor_type=AuditActor.system,
            actor_user_id=None,
        )
    return True


async def _notify_done(notifier: Notifier, request: VerificationRequest, org: Organization) -> None:
    await notifier.send(
        request.submitted_by, texts.VERIFY_DONE.format(org=org.name), f"org_{org.id}"
    )


async def check_site(request: VerificationRequest, fetch: Fetch) -> dict[str, Any]:
    """Код на странице: точное вхождение в HTML или текст."""
    at = utcnow().isoformat()
    if not request.site_url or not request.code:
        return {"ok": False, "message": "Не указана ссылка на сайт", "at": at}
    try:
        page = await fetch(request.site_url)
    except (UnsafeUrlError, FetchError) as exc:
        return {"ok": False, "message": str(exc), "at": at}
    found = request.code in page.html or request.code in page.text
    message = "Код найден" if found else f"Код {request.code} на странице не найден"
    return {"ok": found, "message": message, "at": at, "final_url": page.url}


async def run_checks(
    session: AsyncSession,
    request_id: int,
    *,
    notifier: Notifier,
    fetch: Fetch = fetch_page,
) -> VerificationRequest | None:
    """Задача воркера: проверить код на сайте и завершить заявку, если всё пройдено."""
    request = await session.get(VerificationRequest, request_id)
    if request is None or request.status != VerificationStatus.pending:
        return request
    if request.method != VerificationMethod.registry_auto:
        return request
    org = await session.get(Organization, request.org_id)
    if org is None:
        return request

    before = (request.site_check or {}).get("ok")
    request.site_check = await check_site(request, fetch)
    after = request.site_check.get("ok")
    await audit.record(
        session,
        action="verification.check",
        entity_type="verification_request",
        entity_id=request.id,
        actor_type=AuditActor.system,
        diff=audit.changes({"site": before}, {"site": after}),
    )
    done = await try_finalize(session, request, org)
    await session.commit()
    if done:
        await notifier.moderation_closed("v", request.id)
        await _notify_done(notifier, request, org)
    else:
        reasons = [step.message for step in steps_of(request) if step.status == "failed"]
        if reasons:
            await notifier.send(
                request.submitted_by,
                texts.VERIFY_STEP_FAILED.format(
                    org=org.name, reasons="\n".join(f"• {r}" for r in reasons if r)
                ),
                f"org_{org.id}",
            )
    return request


# --- Заявки ----------------------------------------------------------------------------


def _step_status(ok: object) -> Literal["ok", "failed", "pending"]:
    if ok is True:
        return "ok"
    if ok is False:
        return "failed"
    return "pending"


def steps_of(request: VerificationRequest) -> list[VerificationStep]:
    if request.method == VerificationMethod.manual:
        return [
            VerificationStep(
                code="admin",
                title="Решение администратора",
                status=(
                    "ok"
                    if request.status == VerificationStatus.verified
                    else "failed"
                    if request.status == VerificationStatus.rejected
                    else "pending"
                ),
                message=request.decision_reason,
            )
        ]
    registry = request.registry_snapshot or {}
    site = request.site_check or {}
    return [
        VerificationStep(
            code="registry",
            title="ИНН без ошибок",
            status=_step_status(registry.get("ok")),
            message=registry.get("message"),
        ),
        VerificationStep(
            code="phone",
            title="Телефон подтверждён в боте",
            status="ok" if request.phone_verified else "pending",
            message=None
            if request.phone_verified
            else "Нажми «📱 Подтвердить телефон» в чате с ботом",
        ),
        VerificationStep(
            code="site_code",
            title="Код на сайте организации",
            status=_step_status(site.get("ok")),
            message=site.get("message")
            or f"Размести код {request.code} на странице и нажми «Проверить»",
        ),
    ]


def to_out(request: VerificationRequest) -> VerificationOut:
    next_at = (
        request.last_attempt_at + RETRY_INTERVAL
        if request.last_attempt_at is not None and request.status == VerificationStatus.pending
        else None
    )
    return VerificationOut(
        id=request.id,
        org_id=request.org_id,
        method=request.method,
        status=request.status,
        code=request.code,
        site_url=request.site_url,
        steps=steps_of(request),
        decision_reason=request.decision_reason,
        created_at=request.created_at,
        last_attempt_at=request.last_attempt_at,
        next_attempt_at=next_at,
    )


async def latest(session: AsyncSession, org_id: int) -> VerificationRequest | None:
    request: VerificationRequest | None = await session.scalar(
        select(VerificationRequest)
        .where(VerificationRequest.org_id == org_id)
        .order_by(VerificationRequest.created_at.desc(), VerificationRequest.id.desc())
        .limit(1)
    )
    return request


async def get_for_owner(
    session: AsyncSession, user: User, org_id: int, *, admin: bool = False
) -> VerificationRequest | None:
    await orgs_service.require_owner(session, org_id, user, admin=admin)
    return await latest(session, org_id)


async def _pending(session: AsyncSession, org_id: int) -> VerificationRequest | None:
    request: VerificationRequest | None = await session.scalar(
        select(VerificationRequest)
        .where(
            VerificationRequest.org_id == org_id,
            VerificationRequest.status == VerificationStatus.pending,
        )
        .with_for_update()
    )
    return request


async def start(
    session: AsyncSession,
    user: User,
    org_id: int,
    body: VerificationStart,
    *,
    notifier: Notifier,
) -> VerificationRequest:
    """Подать заявку. ИНН проверяется сразу; телефон — в боте; сайт — по «Проверить»."""
    access = await orgs_service.require_owner(session, org_id, user)
    org = access.org
    if orgs_service.is_verified(org):
        raise AppError("already_verified", "Организация уже проверена", status_code=409)
    if body.inn and not inn_valid(body.inn):
        raise _bad_inn()
    existing = await _pending(session, org_id)
    if existing is not None:
        if existing.method != body.method:
            raise AppError(
                "verification_pending",
                "Уже есть заявка на проверку — дождись результата",
                status_code=409,
            )
        changed: dict[str, Any] = {}
        if body.site_url and body.site_url != existing.site_url:
            changed["site_url"] = [existing.site_url, body.site_url]
            existing.site_url = body.site_url
            existing.site_check = None
        if body.inn and body.inn != existing.inn:
            changed["inn"] = [existing.inn, body.inn]
            existing.inn = body.inn
            existing.registry_snapshot = check_inn(body.inn)
        if changed:
            await audit.record(
                session,
                action="verification.update",
                entity_type="verification_request",
                entity_id=existing.id,
                actor_user_id=user.id,
                diff=changed,
            )
        await session.commit()
        return existing

    request = VerificationRequest(
        org_id=org.id,
        submitted_by=user.id,
        method=body.method,
        status=VerificationStatus.pending,
        phone_verified=False,
    )
    if body.method == VerificationMethod.registry_auto:
        inn = body.inn or org.inn
        site_url = body.site_url or org.website or org.vk_url
        missing = [name for name, value in (("inn", inn), ("site_url", site_url)) if not value]
        if missing:
            raise AppError(
                "validation_error",
                "Для автоматической проверки нужны ИНН и ссылка на сайт или страницу ВК",
                status_code=422,
                details={"missing": missing},
            )
        assert inn is not None  # noqa: S101 — проверено выше
        if not inn_valid(inn):
            raise _bad_inn()
        request.inn = inn
        request.site_url = site_url
        request.code = new_code()
        if org.inn is None:
            org.inn = inn
        request.registry_snapshot = check_inn(inn)
    else:
        request.inn = body.inn or org.inn
        request.site_url = body.site_url or org.website
        request.decision_reason = None
    session.add(request)
    org.verification_status = VerificationStatus.pending
    await session.flush()
    await audit.record(
        session,
        action="verification.submit",
        entity_type="verification_request",
        entity_id=request.id,
        actor_user_id=user.id,
        diff={
            "org_id": org.id,
            "method": body.method,
            "registry_ok": (request.registry_snapshot or {}).get("ok"),
            "comment": body.comment,
        },
    )
    await session.commit()
    # Каждая новая заявка организации — модераторам в бот, любым способом проверки.
    await notifier.alert_moderators("v", request.id)
    if body.method == VerificationMethod.manual:
        await notifier.send(
            user.id, texts.VERIFY_MANUAL_QUEUED.format(org=org.name), f"org_{org.id}"
        )
    return request


async def recheck(
    session: AsyncSession, user: User, org_id: int, jobs: JobQueue
) -> VerificationRequest:
    await orgs_service.require_owner(session, org_id, user)
    request = await _pending(session, org_id)
    if request is None or request.method != VerificationMethod.registry_auto:
        raise AppError("no_pending_request", "Нет заявки на автоматическую проверку", 404)
    now = utcnow()
    if request.last_attempt_at is not None and now - request.last_attempt_at < RETRY_INTERVAL:
        wait_min = int((request.last_attempt_at + RETRY_INTERVAL - now).total_seconds() // 60) + 1
        raise AppError(
            "too_early",
            f"Повторить проверку можно через {wait_min} мин",
            status_code=429,
            details={
                "retry_after_s": int(
                    (request.last_attempt_at + RETRY_INTERVAL - now).total_seconds()
                )
            },
        )
    request.last_attempt_at = now
    await audit.record(
        session,
        action="verification.recheck",
        entity_type="verification_request",
        entity_id=request.id,
        actor_user_id=user.id,
    )
    await session.commit()
    job_id = f"verify:{request.id}:{int(now.timestamp())}"
    await jobs.enqueue(CHECK_VERIFICATION, request.id, job_id=job_id)
    return request


async def decide(
    session: AsyncSession,
    admin_user: User,
    request_id: int,
    approve: bool,
    reason: str | None,
    notifier: Notifier,
) -> VerificationRequest:
    """Способ C: решение администратора по заявке (любого метода)."""
    request = await session.get(VerificationRequest, request_id, with_for_update=True)
    if request is None:
        raise AppError("verification_not_found", "Заявка не найдена", status_code=404)
    if request.status != VerificationStatus.pending:
        raise AppError(
            "already_decided",
            "По заявке уже есть решение",
            status_code=409,
            details={"status": str(request.status)},
        )
    org = await session.get(Organization, request.org_id, with_for_update=True)
    if org is None:
        raise AppError("org_not_found", "Организация не найдена", status_code=404)
    if not approve and not (reason and reason.strip()):
        raise AppError("reason_required", "Укажи причину отказа", status_code=422)
    new_status = VerificationStatus.verified if approve else VerificationStatus.rejected
    request.status = new_status
    request.decided_by = admin_user.id
    request.decided_at = utcnow()
    request.decision_reason = reason.strip() if reason else None
    await audit.record(
        session,
        action="verification.decision",
        entity_type="verification_request",
        entity_id=request.id,
        actor_type=AuditActor.admin,
        actor_user_id=admin_user.id,
        diff={
            "status": [VerificationStatus.pending, new_status],
            "reason": request.decision_reason,
        },
    )
    if approve:
        await orgs_service.mark_verified(
            session,
            org,
            VerificationMethod.manual,
            actor_type=AuditActor.admin,
            actor_user_id=admin_user.id,
        )
    elif org.verification_status == VerificationStatus.pending:
        org.verification_status = VerificationStatus.rejected
    await session.commit()
    await notifier.moderation_closed("v", request.id)
    if approve:
        await _notify_done(notifier, request, org)
    else:
        await notifier.send(
            request.submitted_by,
            texts.VERIFY_REJECTED.format(org=org.name, reason=request.decision_reason),
            f"org_{org.id}",
        )
    return request


async def pending_for_admin(
    session: AsyncSession, limit: int = 20
) -> list[tuple[VerificationRequest, Organization]]:
    rows = await session.execute(
        select(VerificationRequest, Organization)
        .join(Organization, Organization.id == VerificationRequest.org_id)
        .where(VerificationRequest.status == VerificationStatus.pending)
        .order_by(VerificationRequest.created_at, VerificationRequest.id)
        .limit(limit)
    )
    return list(rows.tuples())
