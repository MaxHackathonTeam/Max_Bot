"""Верификация организации (§5.3): B — реестр, телефон, код на сайте, LLM; C — админ.

Способ A (приглашение) — в services.orgs.accept_invite.
"""

import base64
import difflib
import hashlib
import hmac
import re
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
from app.integrations.dadata.party import PartyInfo, PartyRegistry
from app.integrations.safe_fetch import FetchedPage, FetchError, UnsafeUrlError, fetch_page
from app.llm.runner import LlmRunner
from app.llm.schemas import PageCheckOut
from app.models.enums import AuditActor, VerificationMethod, VerificationStatus
from app.models.geo import Locality
from app.models.orgs import Organization, VerificationRequest
from app.models.users import User
from app.schemas.orgs import VerificationOut, VerificationStart, VerificationStep
from app.services import audit
from app.services import orgs as orgs_service
from app.services.events import utcnow
from app.services.notify import Notifier

log = structlog.get_logger(__name__)

RETRY_INTERVAL = timedelta(minutes=10)
NAME_SIMILARITY_MIN = 0.7
PAGE_CONFIDENCE_MIN = 0.7
PAGE_TEXT_LIMIT = 6000
CODE_PREFIX = "AFISHA-"
_CODE_ALPHABET = string.ascii_uppercase + string.digits

# Организационно-правовые формы и служебные слова, не влияющие на сходство названий.
_OPF_WORDS = frozenset(
    """ооо оао пао зао ао ип нко ано ано мбу мбук мку мкук мау мбоу мбудо гбу гбук гау гаук
    фгбу фгбук фгбоу оо роо моо тос нп чу учреждение муниципальное государственное бюджетное
    казенное казённое автономное областное краевое районное городское сельское
    общество ограниченной ответственностью индивидуальный предприниматель культуры
    некоммерческая организация""".split()
)
_NON_WORD = re.compile(r"[^\w\s]+")

Fetch = Callable[[str], Awaitable[FetchedPage]]


def new_code() -> str:
    return CODE_PREFIX + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def normalize_name(name: str) -> str:
    cleaned = _NON_WORD.sub(" ", name.lower().replace("ё", "е"))
    return " ".join(w for w in cleaned.split() if w not in _OPF_WORDS)


def name_similarity(entered: str, party: PartyInfo) -> float:
    target = normalize_name(entered)
    candidates = {
        normalize_name(n) for n in (*party.names_plain, party.name_full, party.name_short) if n
    }
    return max(
        (difflib.SequenceMatcher(None, target, c).ratio() for c in candidates if c),
        default=0.0,
    )


# --- Шаг 1: реестр ---------------------------------------------------------------------


async def _region_matches(session: AsyncSession, org: Organization, party: PartyInfo) -> bool:
    if org.locality_id is None:
        return False
    locality = await session.get(Locality, org.locality_id)
    if locality is None:
        return False
    if locality.region_code and party.region_code:
        return locality.region_code == party.region_code
    if locality.region and party.region:
        return normalize_name(locality.region) == normalize_name(party.region)
    return False


async def check_registry(
    session: AsyncSession, org: Organization, inn: str, registry: PartyRegistry | None
) -> dict[str, Any]:
    """Снимок для registry_snapshot: {ok, message, ...данные реестра}."""
    checked_at = utcnow().isoformat()
    if registry is None:
        return {"ok": None, "message": "Реестр сейчас недоступен, повтори позже", "at": checked_at}
    try:
        party = await registry.find_by_inn(inn)
    except Exception as exc:
        log.warning("verification_registry_failed", error=type(exc).__name__)
        return {"ok": None, "message": "Реестр сейчас недоступен, повтори позже", "at": checked_at}
    if party is None:
        return {"ok": False, "message": f"ИНН {inn} не найден в ЕГРЮЛ/ЕГРИП", "at": checked_at}
    similarity = round(name_similarity(org.name, party), 3)
    region_ok = await _region_matches(session, org, party)
    snapshot: dict[str, Any] = {
        "at": checked_at,
        "inn": party.inn,
        "ogrn": party.ogrn,
        "type": party.kind,
        "status": party.status,
        "name": party.display_name,
        "region": party.region,
        "region_code": party.region_code,
        "name_similarity": similarity,
        "region_match": region_ok,
        "raw": party.raw,
    }
    problems = []
    if party.status != "ACTIVE":
        problems.append("организация в реестре не действующая")
    if similarity < NAME_SIMILARITY_MIN:
        problems.append(f"название не совпадает с реестром («{party.display_name}»)")
    if org.locality_id is None:
        problems.append("укажи населённый пункт организации")
    elif not region_ok:
        problems.append("регион в реестре не совпадает с регионом организации")
    snapshot["ok"] = not problems
    snapshot["message"] = "; ".join(problems) if problems else "Найдена в реестре, действующая"
    return snapshot


def apply_registry(org: Organization, snapshot: dict[str, Any]) -> None:
    if snapshot.get("ok"):
        org.ogrn = snapshot.get("ogrn")
        org.registry_name = snapshot.get("name")
        org.registry_status = snapshot.get("status")


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


# --- Шаги 3–4: код на сайте и LLM-проверка страницы ---------------------------------------


def _all_ok(request: VerificationRequest) -> bool:
    return bool(
        (request.registry_snapshot or {}).get("ok")
        and request.phone_verified
        and (request.site_check or {}).get("ok")
        and (request.llm_check or {}).get("ok")
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


async def check_site(request: VerificationRequest, fetch: Fetch) -> tuple[dict[str, Any], str]:
    """Код на странице; возвращает (site_check, текст страницы для LLM)."""
    at = utcnow().isoformat()
    if not request.site_url or not request.code:
        return {"ok": False, "message": "Не указана ссылка на сайт", "at": at}, ""
    try:
        page = await fetch(request.site_url)
    except UnsafeUrlError as exc:
        return {"ok": False, "message": str(exc), "at": at}, ""
    except FetchError as exc:
        return {"ok": False, "message": str(exc), "at": at}, ""
    text = page.text
    found = request.code in page.html or request.code in text
    message = "Код найден" if found else f"Код {request.code} на странице не найден"
    return {"ok": found, "message": message, "at": at, "final_url": page.url}, text


async def check_page(
    llm: LlmRunner, org: Organization, request: VerificationRequest, page_text: str
) -> dict[str, Any]:
    at = utcnow().isoformat()
    result = await llm.run_json(
        "verification_page",
        "org_page_check",
        PageCheckOut,
        org_name=org.name,
        registry_name=org.registry_name or (request.registry_snapshot or {}).get("name"),
        url=request.site_url,
        page_text=page_text[:PAGE_TEXT_LIMIT],
    )
    base = {"at": at, "prompt_version": result.prompt_version, "model": result.model}
    if result.status == "unavailable":
        return {
            **base,
            "ok": None,
            "message": "Автопроверка страницы недоступна — заявку посмотрит администратор",
        }
    if result.value is None:
        return {
            **base,
            "ok": None,
            "message": "Автопроверка не дала ответа — заявку посмотрит администратор",
        }
    value = result.value
    ok = value.belongs and value.confidence >= PAGE_CONFIDENCE_MIN
    return {
        **base,
        "ok": ok,
        "belongs": value.belongs,
        "confidence": value.confidence,
        "reason": value.reason,
        "message": "Страница относится к организации"
        if ok
        else "Не похоже, что страница принадлежит этой организации",
    }


async def run_checks(
    session: AsyncSession,
    request_id: int,
    *,
    registry: PartyRegistry | None,
    llm: LlmRunner,
    notifier: Notifier,
    fetch: Fetch = fetch_page,
) -> VerificationRequest | None:
    """Задача воркера: всё, что ещё не пройдено. Реестр — повторно, если не прошёл."""
    request = await session.get(VerificationRequest, request_id)
    if request is None or request.status != VerificationStatus.pending:
        return request
    if request.method != VerificationMethod.registry_auto:
        return request
    org = await session.get(Organization, request.org_id)
    if org is None:
        return request

    before = {
        "registry": (request.registry_snapshot or {}).get("ok"),
        "site": (request.site_check or {}).get("ok"),
        "page": (request.llm_check or {}).get("ok"),
    }
    if not (request.registry_snapshot or {}).get("ok") and request.inn:
        snapshot = await check_registry(session, org, request.inn, registry)
        request.registry_snapshot = snapshot
        apply_registry(org, snapshot)
    site_check, page_text = await check_site(request, fetch)
    request.site_check = site_check
    if site_check.get("ok"):
        request.llm_check = await check_page(llm, org, request, page_text)
    after = {
        "registry": (request.registry_snapshot or {}).get("ok"),
        "site": (request.site_check or {}).get("ok"),
        "page": (request.llm_check or {}).get("ok"),
    }
    await audit.record(
        session,
        action="verification.check",
        entity_type="verification_request",
        entity_id=request.id,
        actor_type=AuditActor.system,
        diff=audit.changes(before, after),
    )
    done = await try_finalize(session, request, org)
    await session.commit()
    if done:
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
    page = request.llm_check or {}
    site_ok = site.get("ok") is True
    return [
        VerificationStep(
            code="registry",
            title="ИНН в реестре, название и регион",
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
        VerificationStep(
            code="page_check",
            title="Страница относится к организации",
            status=_step_status(page.get("ok")) if site_ok else "skipped",
            message=page.get("message") if site_ok else None,
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
    registry: PartyRegistry | None,
    notifier: Notifier,
) -> VerificationRequest:
    """Подать заявку. Реестр проверяется сразу; телефон — в боте; сайт — по «Проверить»."""
    access = await orgs_service.require_owner(session, org_id, user)
    org = access.org
    if orgs_service.is_verified(org):
        raise AppError("already_verified", "Организация уже проверена", status_code=409)
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
            existing.llm_check = None
        if body.inn and body.inn != existing.inn:
            changed["inn"] = [existing.inn, body.inn]
            existing.inn = body.inn
            existing.registry_snapshot = None
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
        request.inn = inn
        request.site_url = site_url
        request.code = new_code()
        if org.inn is None:
            org.inn = inn
        snapshot = await check_registry(session, org, inn, registry)
        request.registry_snapshot = snapshot
        apply_registry(org, snapshot)
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
        raise AppError("already_decided", "По заявке уже есть решение", status_code=409)
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
