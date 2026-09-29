"""Публикация событий (FR-PUB), модерация (§6), жалобы, админ-очередь, медиа."""

import io
from datetime import timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs import MODERATE_EVENT
from app.models.enums import EventStatus
from app.models.events import Event
from app.models.system import ModerationDecision
from app.services import moderation
from app.services.events import utcnow
from app.services.notify import MemoryNotifier
from tests.factories import make_locality, make_org, make_venue, random_area
from tests.helpers import login_as

ORG_CONSENTS = ("terms", "privacy", "org_pd")


def _future(hours: float = 48) -> str:
    return (utcnow() + timedelta(hours=hours)).isoformat()


async def _place(db_session: AsyncSession) -> tuple[int, int]:
    lat, lon = random_area()
    locality = await make_locality(db_session, "Событийное", lat, lon)
    venue = await make_venue(db_session, locality, lat, lon, name="Клуб")
    await db_session.commit()
    return locality.id, venue.id


def _body(venue_id: int, **extra: Any) -> dict[str, Any]:
    return {
        "title": "Вечер народной песни",
        "description": "Приходите всей семьёй, будет хор и чай с пирогами.",
        "category": "concert",
        "venue_id": venue_id,
        "price_type": "free",
        "age_rating": 0,
        "sessions": [{"starts_at": _future()}],
        **extra,
    }


async def _create(
    client: httpx.AsyncClient, headers: dict[str, str], body: dict[str, Any]
) -> dict[str, Any]:
    r = await client.post("/api/v1/events", json=body, headers=headers)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    assert data["status"] == "draft"
    return data


async def _verified_org(client: httpx.AsyncClient, owner: dict[str, str]) -> int:
    admin, _ = await login_as(client, 777)
    org = (
        await client.post(
            "/api/v1/orgs", json={"name": "ДК Событийное", "kind": "dk"}, headers=owner
        )
    ).json()
    request = (
        await client.post(
            f"/api/v1/orgs/{org['id']}/verification", json={"method": "manual"}, headers=owner
        )
    ).json()
    r = await client.post(
        f"/api/v1/admin/verifications/{request['id']}/decision",
        json={"action": "approve"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    org_id: int = org["id"]
    return org_id


async def _moderate(db_app: FastAPI, event_id: int) -> str | None:
    async with db_app.state.db() as session:
        return await moderation.moderate_event(session, event_id, notifier=MemoryNotifier())


async def _approve(db_client: httpx.AsyncClient, event_id: int) -> None:
    """Публикует только администратор (§6)."""
    admin, _ = await login_as(db_client, 777)
    r = await db_client.post(
        f"/api/v1/admin/events/{event_id}/decision", json={"action": "approve"}, headers=admin
    )
    assert r.status_code == 204, r.text


async def test_community_flow_by_rules(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    stranger, _ = await login_as(db_client)
    event = await _create(db_client, author, _body(venue_id))
    assert event["trust_tier"] == "community" and event["can_pushkin"] is False

    # Черновик виден только автору; чужой не может читать и менять.
    assert (await db_client.get(f"/api/v1/events/{event['id']}")).status_code == 404
    url = f"/api/v1/events/{event['id']}"
    assert (await db_client.get(f"{url}/manage", headers=stranger)).status_code == 403
    r = await db_client.patch(url, json={"title": "Чужое"}, headers=stranger)
    assert r.status_code == 403
    assert (await db_client.post(f"{url}/submit", headers=stranger)).status_code == 403

    r = await db_client.patch(url, json={"short_description": "Хор и чай"}, headers=author)
    assert r.status_code == 200 and r.json()["short_description"] == "Хор и чай"

    r = await db_client.post(f"{url}/submit", headers=author)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    jobs = db_app.state.jobs
    assert [j.args[0] for j in jobs.named(MODERATE_EVENT)] == [event["id"]]
    assert (await db_client.post(f"{url}/submit", headers=author)).status_code == 409

    # Чистое по правилам событие не публикуется само — ждёт администратора.
    assert await _moderate(db_app, event["id"]) == "pending"
    assert (await db_client.get(url)).status_code == 404
    await _approve(db_client, event["id"])
    # Задача после решения ничего не меняет.
    assert await _moderate(db_app, event["id"]) is None
    public = await db_client.get(url)
    assert public.status_code == 200 and public.json()["trust_tier"] == "community"
    decisions = await db_session.scalars(
        select(ModerationDecision.actor_type).where(
            ModerationDecision.entity_type == "event", ModerationDecision.entity_id == event["id"]
        )
    )
    assert set(decisions) == {"rules", "admin"}

    mine = (await db_client.get("/api/v1/me/events", headers=author)).json()
    assert [(e["id"], e["status"]) for e in mine] == [(event["id"], "published")]

    # Существенная правка опубликованного community-события — снова на проверку.
    r = await db_client.patch(url, json={"title": "Вечер песни и танцев"}, headers=author)
    assert r.status_code == 200 and r.json()["status"] == "pending"


async def test_suspicious_waits_for_admin(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    body = _body(venue_id, title="ВЕЧЕР НАРОДНОЙ ПЕСНИ", description="Приходите!!!")
    event = await _create(db_client, author, body)
    await db_client.post(f"/api/v1/events/{event['id']}/submit", headers=author)
    # Подозрительное по правилам не публикуется сразу — ждёт администратора с причинами.
    assert await _moderate(db_app, event["id"]) == "pending"
    manage = (await db_client.get(f"/api/v1/events/{event['id']}/manage", headers=author)).json()
    assert manage["status"] == "pending" and "заглавными" in manage["moderation_reason"]

    admin, _ = await login_as(db_client, 777)
    queue = (await db_client.get("/api/v1/admin/queue", headers=admin)).json()
    assert event["id"] in [e["id"] for e in queue["events"]]
    decision = f"/api/v1/admin/events/{event['id']}/decision"
    assert (
        await db_client.post(decision, json={"action": "approve"}, headers=author)
    ).status_code == 403
    r = await db_client.post(decision, json={"action": "approve"}, headers=admin)
    assert r.status_code == 204
    r = await db_client.post(decision, json={"action": "approve"}, headers=admin)
    assert r.status_code == 409
    assert (await db_client.get(f"/api/v1/events/{event['id']}")).status_code == 200


async def test_submit_validation(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)

    empty = await _create(db_client, author, {"title": "Без полей"})
    r = await db_client.post(f"/api/v1/events/{empty['id']}/submit", headers=author)
    assert r.status_code == 422
    fields = {f["field"] for f in r.json()["error"]["details"]["fields"]}
    assert {"category", "venue_id", "price_type"} <= fields

    pushkin = await _create(
        db_client, author, _body(venue_id, pushkin_card=True, title="Спектакль")
    )
    r = await db_client.post(f"/api/v1/events/{pushkin['id']}/submit", headers=author)
    assert r.status_code == 422
    assert "pushkin_card" in {f["field"] for f in r.json()["error"]["details"]["fields"]}

    spam = await _create(
        db_client, author, _body(venue_id, title="Турнир", description="Лучшее онлайн-казино")
    )
    r = await db_client.post(f"/api/v1/events/{spam['id']}/submit", headers=author)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["moderation_reason"]


async def test_community_limits(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    when = [{"starts_at": _future()}]
    first = await _create(db_client, author, _body(venue_id, sessions=when))
    assert (
        await db_client.post(f"/api/v1/events/{first['id']}/submit", headers=author)
    ).status_code == 200

    twin = await _create(db_client, author, _body(venue_id, sessions=when))
    r = await db_client.post(f"/api/v1/events/{twin['id']}/submit", headers=author)
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate"

    for i in range(2):
        e = await _create(db_client, author, _body(venue_id, title=f"Встреча клуба №{i + 2}"))
        assert (
            await db_client.post(f"/api/v1/events/{e['id']}/submit", headers=author)
        ).status_code == 200
    extra = await _create(db_client, author, _body(venue_id, title="Четвёртая встреча"))
    r = await db_client.post(f"/api/v1/events/{extra['id']}/submit", headers=author)
    assert r.status_code == 429


async def test_official_flow_and_team(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    owner, _ = await login_as(db_client, consents=ORG_CONSENTS)
    outsider, _ = await login_as(db_client)
    org_id = await _verified_org(db_client, owner)

    r = await db_client.post(
        "/api/v1/events", json=_body(venue_id, organization_id=org_id), headers=outsider
    )
    assert r.status_code == 403

    event = await _create(
        db_client, owner, _body(venue_id, organization_id=org_id, pushkin_card=True)
    )
    assert event["trust_tier"] == "official" and event["can_pushkin"] is True
    r = await db_client.post(f"/api/v1/events/{event['id']}/submit", headers=owner)
    # Официальное тоже ждёт модератора: сразу не публикуется.
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert (await db_client.get(f"/api/v1/events/{event['id']}")).status_code == 404
    assert await _moderate(db_app, event["id"]) == "pending"
    await _approve(db_client, event["id"])
    assert (await db_client.get(f"/api/v1/events/{event['id']}")).json()["pushkin_card"] is True
    manage = await db_client.get(f"/api/v1/events/{event['id']}/manage", headers=owner)
    assert manage.json()["published_at"] is not None
    listed = (
        await db_client.get(
            f"/api/v1/orgs/{org_id}/events", params={"status": "published"}, headers=owner
        )
    ).json()
    assert [e["id"] for e in listed] == [event["id"]]

    r = await db_client.post(f"/api/v1/events/{event['id']}/cancel", headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert (
        await db_client.delete(f"/api/v1/events/{event['id']}", headers=owner)
    ).status_code == 409


async def test_admin_delete_event(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    event = await _create(db_client, author, _body(venue_id))
    url = f"/api/v1/admin/events/{event['id']}"
    assert (await db_client.delete(url, headers=author)).status_code == 403
    admin, _ = await login_as(db_client, 777)
    r = await db_client.delete(url, params={"reason": "Дубль"}, headers=admin)
    assert r.status_code == 204
    assert await db_session.get(Event, event["id"]) is None
    r = await db_client.delete(url, headers=admin)
    assert r.status_code == 404 and r.json()["error"]["code"] == "event_not_found"


async def test_delete_draft(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    event = await _create(db_client, author, _body(venue_id))
    assert (
        await db_client.delete(f"/api/v1/events/{event['id']}", headers=author)
    ).status_code == 204
    assert await db_session.get(Event, event["id"]) is None


async def test_reports_hide_event(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    event = await _create(db_client, author, _body(venue_id))
    await db_client.post(f"/api/v1/events/{event['id']}/submit", headers=author)
    await _moderate(db_app, event["id"])
    await _approve(db_client, event["id"])
    url = f"/api/v1/events/{event['id']}/report"

    first, _ = await login_as(db_client)
    r = await db_client.post(url, json={"reason": "fraud"}, headers=first)
    assert r.status_code == 200 and r.json() == {"accepted": True}
    r = await db_client.post(url, json={"reason": "fraud"}, headers=first)
    assert r.json() == {"accepted": False}
    for _ in range(2):
        headers, _ = await login_as(db_client)
        await db_client.post(url, json={"reason": "wrong_data"}, headers=headers)

    hidden = await db_session.get(Event, event["id"], populate_existing=True)
    assert hidden is not None and hidden.status == EventStatus.hidden
    assert (await db_client.get(f"/api/v1/events/{event['id']}")).status_code == 404


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 50, 50)).save(buffer, "PNG")
    return buffer.getvalue()


async def test_media_upload_and_cover(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    other, _ = await login_as(db_client)
    r = await db_client.post(
        "/api/v1/media", files={"file": ("cover.png", _png(), "image/png")}, headers=author
    )
    assert r.status_code == 201, r.text
    media = r.json()
    assert media["url"].startswith("/media/")

    bad = await db_client.post(
        "/api/v1/media", files={"file": ("x.png", b"not an image", "image/png")}, headers=author
    )
    assert bad.status_code == 415

    r = await db_client.post(
        "/api/v1/events", json=_body(venue_id, cover_media_id=media["id"]), headers=other
    )
    assert r.status_code == 422  # чужая картинка
    assert r.json()["error"]["details"]["fields"][0]["field"] == "cover_media_id"
    event = await _create(db_client, author, _body(venue_id, cover_media_id=media["id"]))
    assert event["cover_url"] == media["url"]
    served = await db_client.get(media["url"])
    assert served.status_code == 200 and served.content[:4] == b"RIFF"


async def test_admin_card_and_moderation_rights(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    author, author_me = await login_as(db_client)
    stranger, _ = await login_as(db_client)
    admin, _ = await login_as(db_client, 777)
    body = _body(venue_id, title="ВЕЧЕР НАРОДНОЙ ПЕСНИ", description="Приходите!!!")
    event = await _create(db_client, author, body)
    await db_client.post(f"/api/v1/events/{event['id']}/submit", headers=author)
    assert await _moderate(db_app, event["id"]) == "pending"

    card_url = f"/api/v1/admin/events/{event['id']}"
    decision = f"{card_url}/decision"
    # Карточка, очередь и решения — только администраторам из ADMIN_MAX_USER_IDS.
    assert (await db_client.get(card_url)).status_code == 401
    for headers in (author, stranger):
        assert (await db_client.get(card_url, headers=headers)).status_code == 403
        assert (await db_client.get("/api/v1/admin/queue", headers=headers)).status_code == 403
        r = await db_client.post(
            decision, json={"action": "reject", "reason": "x"}, headers=headers
        )
        assert r.status_code == 403
    assert (await db_client.get("/api/v1/admin/events/0", headers=admin)).status_code == 404

    r = await db_client.get(card_url, headers=admin)
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["event"]["id"] == event["id"] and card["event"]["status"] == "pending"
    assert card["author"] == {
        "id": author_me["id"],
        "name": author_me["first_name"],
        "max_user_id": author_me["max_user_id"],
    }
    signals = [f["message"] for f in card["flags"] if f["kind"] == "signal"]
    assert "название заглавными буквами" in signals
    assert [d["actor_type"] for d in card["decisions"]] == ["rules"]
    actions = [h["action"] for h in card["history"]]
    assert "event.create" in actions
    assert [h["id"] for h in card["history"]] == sorted(
        (h["id"] for h in card["history"]), reverse=True
    )

    # Отказ — только с причиной; причина видна автору и в истории решений.
    r = await db_client.post(decision, json={"action": "reject"}, headers=admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = await db_client.post(
        decision, json={"action": "reject", "reason": "Уточни дату"}, headers=admin
    )
    assert r.status_code == 204
    card = (await db_client.get(card_url, headers=admin)).json()
    assert card["event"]["status"] == "rejected"
    assert card["event"]["moderation_reason"] == "Уточни дату"
    assert [d["actor_type"] for d in card["decisions"]] == ["admin", "rules"]
    mine = (await db_client.get("/api/v1/me/events", headers=author)).json()
    assert [(e["id"], e["status"]) for e in mine] == [(event["id"], "rejected")]


async def test_precheck_return_and_queue_filter(
    db_app: FastAPI, db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _, venue_id = await _place(db_session)
    author, _ = await login_as(db_client)
    body = _body(venue_id, title="ВЕЧЕР НАРОДНОЙ ПЕСНИ", description="Звоните +7 900 123-45-67")
    event = await _create(db_client, author, body)
    url = f"/api/v1/events/{event['id']}"

    # Проверка до отправки ничего не меняет и показывает те же правила, что submit.
    check = (await db_client.post(f"{url}/check", headers=author)).json()
    assert "contacts_in_text" in {v["code"] for v in check["violations"]}
    assert "название заглавными буквами" in check["warnings"]
    admin, _ = await login_as(db_client, 777)
    assert (await db_client.post(f"{url}/check", headers=admin)).status_code == 403

    await db_client.patch(url, json={"description": "Приходите всей семьёй!!!"}, headers=author)
    await db_client.post(f"{url}/submit", headers=author)
    assert await _moderate(db_app, event["id"]) == "pending"

    def ids(queue: httpx.Response) -> list[int]:
        return [e["id"] for e in queue.json()["events"]]

    queue_url = "/api/v1/admin/queue"
    assert event["id"] in ids(await db_client.get(f"{queue_url}?filter=new", headers=admin))
    assert event["id"] not in ids(
        await db_client.get(f"{queue_url}?filter=returned", headers=admin)
    )

    decision = f"/api/v1/admin/events/{event['id']}/decision"
    r = await db_client.post(decision, json={"action": "return"}, headers=admin)
    assert r.status_code == 422
    r = await db_client.post(
        decision, json={"action": "return", "reason": "Добавь адрес"}, headers=admin
    )
    assert r.status_code == 204
    manage = (await db_client.get(f"{url}/manage", headers=author)).json()
    assert manage["status"] == "draft" and manage["moderation_reason"] == "Добавь адрес"
    sent = [str(j.args) for j in db_app.state.jobs.jobs]
    assert any("на доработку" in args for args in sent)

    # Повторная отправка — в фильтре «возвращённые».
    await db_client.post(f"{url}/submit", headers=author)
    await _moderate(db_app, event["id"])
    returned = await db_client.get(f"{queue_url}?filter=returned", headers=admin)
    assert event["id"] in ids(returned)
    assert event["id"] not in ids(await db_client.get(f"{queue_url}?filter=new", headers=admin))


async def test_venue_search_hides_foreign_org_venues(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    locality = await make_locality(db_session, "Площадочное", lat, lon)
    await make_venue(db_session, locality, lat, lon, name="Сельский клуб общий")
    foreign = await make_venue(db_session, locality, lat, lon, name="Сельский клуб чужой")
    foreign.org_id = (await make_org(db_session)).id
    await db_session.commit()
    author, _ = await login_as(db_client)

    r = await db_client.get("/api/v1/venues", params={"q": "Сельский клуб"}, headers=author)
    assert r.status_code == 200
    # Чужую площадку выбрать нельзя (_check_refs), поэтому поиск её не предлагает.
    assert [v["name"] for v in r.json()] == ["Сельский клуб общий"]
