"""Организации, команда, приглашения, верификация A/B/C, отзыв (FR-ORG, §5.3)."""

import hashlib
import hmac
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import CHECK_VERIFICATION, REQUEST_PHONE
from app.integrations.safe_fetch import FetchedPage, UnsafeUrlError
from app.models.enums import EventStatus, TrustTier
from app.models.events import Event
from app.models.orgs import VerificationRequest
from app.models.system import AuditLog
from app.models.users import User
from app.services import verification as verification_service
from app.services.notify import MemoryNotifier
from app.services.verification import ContactData
from tests.factories import make_event, make_locality, random_area
from tests.helpers import BOT_TOKEN, login_as

ORG_CONSENTS = ("terms", "privacy", "org_pd")
INN = "7701234560"


async def _locality(db_session: AsyncSession) -> int:
    lat, lon = random_area()
    locality = await make_locality(db_session, "Тестово", lat, lon)
    await db_session.commit()
    return locality.id


async def _create_org(
    client: httpx.AsyncClient, headers: dict[str, str], **fields: Any
) -> dict[str, Any]:
    body = {"name": "Дом культуры села Тестово", "kind": "dk", **fields}
    r = await client.post("/api/v1/orgs", json=body, headers=headers)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def test_org_requires_org_consent(db_client: httpx.AsyncClient) -> None:
    headers, _ = await login_as(db_client)
    r = await db_client.post("/api/v1/orgs", json={"name": "ДК", "kind": "dk"}, headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "consent_required"


async def test_org_crud_and_permissions(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    stranger, _ = await login_as(db_client, consents=ORG_CONSENTS)
    locality_id = await _locality(db_session)
    org = await _create_org(db_client, owner, locality_id=locality_id, phone="+79120000000")
    assert org["my_role"] == "owner"
    assert org["verified"] is False
    assert org["locality_name"] == "Тестово"

    mine = (await db_client.get("/api/v1/orgs/mine", headers=owner)).json()
    assert [o["id"] for o in mine] == [org["id"]]

    # Посторонний видит карточку без контактов и не может её менять.
    public = (await db_client.get(f"/api/v1/orgs/{org['id']}", headers=stranger)).json()
    assert public["phone"] is None and public["my_role"] is None
    r = await db_client.patch(
        f"/api/v1/orgs/{org['id']}", json={"description": "взлом"}, headers=stranger
    )
    assert r.status_code == 403
    assert (
        await db_client.get(f"/api/v1/orgs/{org['id']}/members", headers=stranger)
    ).status_code == 403
    assert (
        await db_client.get(f"/api/v1/orgs/{org['id']}/events", headers=stranger)
    ).status_code == 403

    r = await db_client.patch(
        f"/api/v1/orgs/{org['id']}", json={"description": "Сельский ДК"}, headers=owner
    )
    assert r.status_code == 200 and r.json()["description"] == "Сельский ДК"
    audit = await db_session.scalars(
        select(AuditLog.action).where(
            AuditLog.entity_type == "organization", AuditLog.entity_id == org["id"]
        )
    )
    assert {"org.create", "org.update"} <= set(audit)
    assert (await db_client.get("/api/v1/orgs/404404", headers=owner)).status_code == 404


async def test_invite_flow_and_members(db_client: httpx.AsyncClient) -> None:
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    editor, editor_user = await login_as(db_client, consents=ORG_CONSENTS)
    org = await _create_org(db_client, owner)

    r = await db_client.post(f"/api/v1/orgs/{org['id']}/invites", json={}, headers=editor)
    assert r.status_code == 403
    r = await db_client.post(
        f"/api/v1/orgs/{org['id']}/invites", json={"grants_verification": True}, headers=owner
    )
    assert r.status_code == 403  # верифицирующее приглашение — только админ

    invite = (
        await db_client.post(f"/api/v1/orgs/{org['id']}/invites", json={}, headers=owner)
    ).json()
    assert invite["payload"] == f"inv_{invite['token']}"
    assert invite["url"].endswith(f"startapp=inv_{invite['token']}")

    preview = (await db_client.get(f"/api/v1/invites/{invite['token']}", headers=editor)).json()
    assert preview["valid"] is True and preview["org_name"] == org["name"]
    accepted = await db_client.post(f"/api/v1/invites/{invite['token']}/accept", headers=editor)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"org_id": org["id"], "role": "editor", "verified": False}
    again = await db_client.post(f"/api/v1/invites/{invite['token']}/accept", headers=editor)
    assert again.status_code == 410
    bad = await db_client.get("/api/v1/invites/nonexistent-token-123", headers=editor)
    assert bad.status_code in (404, 410)

    members = (await db_client.get(f"/api/v1/orgs/{org['id']}/members", headers=editor)).json()
    assert {m["role"] for m in members} == {"owner", "editor"}
    owner_id = next(m["user_id"] for m in members if m["role"] == "owner")
    # Последнего владельца убрать нельзя; редактор может выйти сам.
    r = await db_client.delete(f"/api/v1/orgs/{org['id']}/members/{owner_id}", headers=owner)
    assert r.status_code == 409
    r = await db_client.delete(
        f"/api/v1/orgs/{org['id']}/members/{editor_user['id']}", headers=editor
    )
    assert r.status_code == 204


async def test_invite_method_a_verifies(db_client: httpx.AsyncClient) -> None:
    admin, _ = await login_as(db_client, 777, consents=ORG_CONSENTS)
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    org = await _create_org(db_client, owner)
    r = await db_client.post(
        f"/api/v1/orgs/{org['id']}/invites",
        json={"role": "owner", "grants_verification": True},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    accepted = (await db_client.post(f"/api/v1/invites/{token}/accept", headers=owner)).json()
    assert accepted["verified"] is True
    data = (await db_client.get(f"/api/v1/orgs/{org['id']}", headers=owner)).json()
    assert data["verified"] is True and data["verification_method"] == "invite"


async def _run_checks(
    db_app: FastAPI, request_id: int, fetch: Any, notifier: MemoryNotifier
) -> VerificationRequest | None:
    async with db_app.state.db() as session:
        return await verification_service.run_checks(
            session, request_id, notifier=notifier, fetch=fetch
        )


def _contact(vcf: str, max_user_id: int) -> ContactData:
    digest = hmac.new(BOT_TOKEN.encode(), vcf.encode(), hashlib.sha256).hexdigest()
    return ContactData(vcf_info=vcf, hash=digest, max_user_id=max_user_id)


async def test_verification_method_b_full(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner, owner_user = await login_as(db_client, consents=ORG_CONSENTS)
    stranger, _ = await login_as(db_client, consents=ORG_CONSENTS)
    locality_id = await _locality(db_session)
    org = await _create_org(db_client, owner, locality_id=locality_id)
    url = f"/api/v1/orgs/{org['id']}/verification"

    r = await db_client.post(url, json={"method": "registry_auto"}, headers=owner)
    assert r.status_code == 422  # нужен ИНН и сайт
    r = await db_client.post(
        url, json={"inn": INN, "site_url": "https://dk.test/"}, headers=stranger
    )
    assert r.status_code == 403

    r = await db_client.post(url, json={"inn": INN, "site_url": "https://dk.test/"}, headers=owner)
    assert r.status_code == 201, r.text
    request = r.json()
    code = request["code"]
    assert code.startswith("AFISHA-")
    steps = {s["code"]: s["status"] for s in request["steps"]}
    assert steps["registry"] == "ok" and steps["phone"] == "pending"
    jobs = db_app.state.jobs
    assert [j.args for j in jobs.named(REQUEST_PHONE)] == [(owner_user["id"], org["id"])]

    # Повторная проверка ставит задачу; вторая — раньше 10 минут — 429.
    r = await db_client.post(f"{url}/recheck", headers=owner)
    assert r.status_code == 202
    assert len(jobs.named(CHECK_VERIFICATION)) == 1
    r = await db_client.post(f"{url}/recheck", headers=owner)
    assert r.status_code == 429
    assert r.json()["error"]["details"]["retry_after_s"] > 0

    notifier = MemoryNotifier()

    async def page_with_code(site: str) -> FetchedPage:
        return FetchedPage(url=site, status=200, html=f"<p>Дом культуры. {code}</p>")

    checked = await _run_checks(db_app, request["id"], page_with_code, notifier)
    assert checked is not None and checked.status == "pending"  # телефон ещё не подтверждён

    user = await db_session.get(User, owner_user["id"])
    assert user is not None
    # Чужой контакт и плохая подпись не проходят.
    async with db_app.state.db() as session:
        other = _contact("BEGIN:VCARD\nEND:VCARD", 1)
        assert (
            await verification_service.confirm_phone(session, user, other, BOT_TOKEN, notifier)
            == "not_own"
        )
        forged = ContactData("BEGIN:VCARD\nEND:VCARD", "00" * 32, user.max_user_id)
        assert (
            await verification_service.confirm_phone(session, user, forged, BOT_TOKEN, notifier)
            == "bad_signature"
        )
        ok = _contact("BEGIN:VCARD\nTEL:+79120000000\nEND:VCARD", user.max_user_id or 0)
        assert (
            await verification_service.confirm_phone(session, user, ok, BOT_TOKEN, notifier) == "ok"
        )

    data = (await db_client.get(f"/api/v1/orgs/{org['id']}", headers=owner)).json()
    assert data["verified"] is True
    assert data["verification_method"] == "registry_auto"
    assert any("проверена" in text for _, text, _ in notifier.sent)
    status = (await db_client.get(url, headers=owner)).json()
    assert status["status"] == "verified"
    assert {s["status"] for s in status["steps"]} == {"ok"}


async def test_verification_b_failures(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    org = await _create_org(db_client, owner, locality_id=await _locality(db_session))
    url = f"/api/v1/orgs/{org['id']}/verification"
    # ИНН проверяется локально по контрольной цифре — без внешних реестров.
    bad = await db_client.post(
        url,
        json={"inn": INN[:-1] + str((int(INN[-1]) + 1) % 10), "site_url": "https://dk.test/"},
        headers=owner,
    )
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "inn"
    r = await db_client.post(url, json={"inn": INN, "site_url": "https://dk.test/"}, headers=owner)
    request = r.json()

    notifier = MemoryNotifier()

    async def ssrf(site: str) -> FetchedPage:
        raise UnsafeUrlError("Адрес сайта ведёт во внутреннюю сеть")

    checked = await _run_checks(db_app, request["id"], ssrf, notifier)
    assert checked is not None and checked.status == "pending"
    assert checked.site_check is not None and checked.site_check["ok"] is False
    assert notifier.sent and "не пройдена" in notifier.sent[-1][1]


async def test_verification_manual_and_admin_decision(
    db_app: FastAPI, db_client: httpx.AsyncClient
) -> None:
    admin, _ = await login_as(db_client, 777)
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    org = await _create_org(db_client, owner)
    r = await db_client.post(
        f"/api/v1/orgs/{org['id']}/verification",
        json={"method": "manual", "comment": "Мы муниципальный ДК"},
        headers=owner,
    )
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]

    assert (await db_client.get("/api/v1/admin/queue", headers=owner)).status_code == 403
    queue = (await db_client.get("/api/v1/admin/queue", headers=admin)).json()
    assert request_id in [v["id"] for v in queue["verifications"]]

    decision = f"/api/v1/admin/verifications/{request_id}/decision"
    r = await db_client.post(decision, json={"action": "reject"}, headers=admin)
    assert r.status_code == 422  # отказ без причины
    r = await db_client.post(decision, json={"action": "approve"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "verified"
    data = (await db_client.get(f"/api/v1/orgs/{org['id']}", headers=owner)).json()
    assert data["verified"] is True and data["verification_method"] == "manual"
    sent = [j.args for j in db_app.state.jobs.named("send_user_message")]
    assert any("проверена" in args[1] for args in sent)


async def test_revoke_moves_events_to_community(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    admin, _ = await login_as(db_client, 777)
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    org_data = await _create_org(db_client, owner)
    r = await db_client.post(
        f"/api/v1/orgs/{org_data['id']}/verification", json={"method": "manual"}, headers=owner
    )
    await db_client.post(
        f"/api/v1/admin/verifications/{r.json()['id']}/decision",
        json={"action": "approve"},
        headers=admin,
    )
    lat, lon = random_area()
    locality = await make_locality(db_session, "Отзывино", lat, lon)
    from app.models.orgs import Organization

    org = await db_session.get(Organization, org_data["id"])
    event = await make_event(db_session, locality, org=org, pushkin_card=True)
    await db_session.commit()

    r = await db_client.post(
        f"/api/v1/admin/orgs/{org_data['id']}/revoke", json={"reason": "жалобы"}, headers=owner
    )
    assert r.status_code == 403
    r = await db_client.post(
        f"/api/v1/admin/orgs/{org_data['id']}/revoke", json={"reason": "жалобы"}, headers=admin
    )
    assert r.status_code == 200 and r.json()["events_moved"] == 1
    moved = await db_session.get(Event, event.id, populate_existing=True)
    assert moved is not None
    assert moved.trust_tier == TrustTier.community and moved.pushkin_card is False
    assert moved.status == EventStatus.published
    data = (await db_client.get(f"/api/v1/orgs/{org_data['id']}", headers=owner)).json()
    assert data["verified"] is False

    page = (
        await db_client.get(
            "/api/v1/admin/audit",
            params={"entity_type": "organization", "entity_id": org_data["id"]},
            headers=admin,
        )
    ).json()
    assert "org.revoke" in [i["action"] for i in page["items"]]
