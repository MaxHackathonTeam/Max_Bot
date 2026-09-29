"""Открытый профиль организации, её афиши и поиск организаций — без токена."""

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.demo.orgs import ORG_NOTE, SEED_USERNAME, org_description
from app.models.enums import EventStatus, OrgKind, TrustTier, VerificationStatus
from app.models.geo import Locality
from app.models.orgs import Organization, OrgMember
from app.models.users import User
from tests.factories import in_hours, make_event, make_locality, make_org, random_area

PRIVATE = ("inn", "ogrn", "phone", "email", "members", "my_role", "registry_name", "created_by")


async def _place(db_session: AsyncSession, name: str = "Орлово") -> Locality:
    lat, lon = random_area()
    return await make_locality(db_session, name, lat, lon)


async def _org(
    db_session: AsyncSession,
    locality: Locality,
    name: str,
    *,
    kind: str = OrgKind.dk,
    status: str = VerificationStatus.verified,
) -> Organization:
    org = await make_org(db_session)
    org.name = name
    org.kind = kind
    org.locality_id = locality.id
    org.verification_status = status
    await db_session.flush()
    return org


async def _get(client: httpx.AsyncClient, url: str, **params: Any) -> dict[str, Any]:
    r = await client.get(url, params=params)
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


async def test_public_profile_without_token_and_without_pd(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    locality = await _place(db_session)
    org = await _org(db_session, locality, "ДК «Родник»")
    org.inn = "7701234560"
    org.ogrn = "1027700132195"
    org.phone = "+79120000000"
    org.email = "dk@example.ru"
    org.description = "Дом культуры: хор, кружки и праздники."
    org.address = "ул. Мира, 1"
    org.website = "https://dk.example.ru"
    member = User(first_name="Иван", last_name="Петров")
    db_session.add(member)
    await db_session.flush()
    db_session.add(OrgMember(org_id=org.id, user_id=member.id, role="owner"))
    await make_event(db_session, locality, title="Концерт хора", org=org, starts=[in_hours(24)])
    await make_event(db_session, locality, title="Прошлый вечер", org=org, starts=[in_hours(-48)])
    await make_event(
        db_session,
        locality,
        title="Черновик",
        org=org,
        status=EventStatus.draft,
        starts=[in_hours(30)],
    )
    await make_event(
        db_session,
        locality,
        title="От жителей",
        org=org,
        trust_tier=TrustTier.community,
        starts=[in_hours(40)],
    )
    await db_session.commit()

    body = await _get(db_client, f"/api/v1/orgs/{org.id}/public")
    assert body["name"] == "ДК «Родник»"
    assert body["description"] == "Дом культуры: хор, кружки и праздники."
    assert body["kind"] == "dk"
    assert body["locality"] == {"id": locality.id, "name": "Орлово"}
    assert body["verified"] is True and body["is_demo"] is False
    assert body["address"] == "ул. Мира, 1" and body["website"] == "https://dk.example.ru"
    assert (body["future_events"], body["official_events"], body["community_events"]) == (2, 1, 1)
    for field in PRIVATE:
        assert field not in body
    raw = str(body)
    for secret in ("7701234560", "1027700132195", "+79120000000", "dk@example.ru", "Петров"):
        assert secret not in raw


async def test_public_events_split_feeds_and_hide_unpublished(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    locality = await _place(db_session)
    org = await _org(db_session, locality, "Музей ремёсел")
    for i in range(3):
        await make_event(
            db_session, locality, title=f"Экскурсия {i}", org=org, starts=[in_hours(10 + i)]
        )
    await make_event(db_session, locality, title="Прошедшая", org=org, starts=[in_hours(-5)])
    await make_event(
        db_session,
        locality,
        title="На модерации",
        org=org,
        status=EventStatus.pending,
        starts=[in_hours(20)],
    )
    await make_event(
        db_session,
        locality,
        title="Сосед",
        org=org,
        trust_tier=TrustTier.community,
        starts=[in_hours(12)],
    )
    # Чужое событие в том же пункте в афиши организации не попадает.
    await make_event(db_session, locality, title="Чужое", starts=[in_hours(11)])
    await db_session.commit()

    url = f"/api/v1/orgs/{org.id}/public/events"
    first = await _get(db_client, url, limit=2)
    assert [e["title"] for e in first["items"]] == ["Экскурсия 0", "Экскурсия 1"]
    assert all(e["trust_tier"] == "official" for e in first["items"])
    assert first["items"][0]["org"] == {"id": org.id, "name": "Музей ремёсел", "verified": True}
    second = await _get(db_client, url, limit=2, cursor=first["next_cursor"])
    assert [e["title"] for e in second["items"]] == ["Экскурсия 2"]
    assert second["next_cursor"] is None

    community = await _get(db_client, url, tier="community")
    assert [e["title"] for e in community["items"]] == ["Сосед"]

    r = await db_client.get(url, params={"tier": "all"})
    assert r.status_code == 422
    r = await db_client.get(url, params={"cursor": "мусор"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"


async def test_revoked_and_missing_orgs_are_hidden(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    locality = await _place(db_session)
    revoked = await _org(db_session, locality, "Отозванный клуб", status=VerificationStatus.revoked)
    await make_event(db_session, locality, org=revoked, starts=[in_hours(5)])
    await db_session.commit()

    for url in (f"/api/v1/orgs/{revoked.id}/public", f"/api/v1/orgs/{revoked.id}/public/events"):
        r = await db_client.get(url)
        assert r.status_code == 404
        error = r.json()["error"]
        assert error["code"] == "org_not_found" and error["message"] == "Организация не найдена"
    r = await db_client.get("/api/v1/orgs/999999999/public")
    assert r.status_code == 404

    found = await _get(db_client, "/api/v1/orgs/search", q="Отозванный", locality_id=locality.id)
    assert found["items"] == []


async def test_search_fuzzy_and_filters(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    locality = await _place(db_session, "Берёзовка")
    other = await _place(db_session, "Сосновка")
    library = await _org(db_session, locality, "Библиотека имени Пушкина", kind=OrgKind.library)
    dk = await _org(
        db_session, locality, "Дом культуры Берёзовка", status=VerificationStatus.unverified
    )
    await _org(db_session, other, "Библиотека семейного чтения", kind=OrgKind.library)
    await make_event(db_session, locality, org=library, starts=[in_hours(3)])
    await db_session.commit()

    search = "/api/v1/orgs/search"
    # Опечатка в названии — нечёткий поиск по pg_trgm.
    typo = await _get(db_client, search, q="библеотека", locality_id=locality.id)
    assert [o["id"] for o in typo["items"]] == [library.id]
    item = typo["items"][0]
    assert item["locality"] == {"id": locality.id, "name": "Берёзовка"}
    assert item["verified"] is True and item["future_events"] == 1
    for field in PRIVATE:
        assert field not in item

    by_kind = await _get(db_client, search, locality_id=locality.id, type="dk")
    assert [o["id"] for o in by_kind["items"]] == [dk.id]
    assert by_kind["items"][0]["verified"] is False

    # Без запроса — все организации пункта, проверенные выше.
    everything = await _get(db_client, search, locality_id=locality.id, limit=1)
    assert [o["id"] for o in everything["items"]] == [library.id]
    rest = await _get(
        db_client, search, locality_id=locality.id, limit=1, cursor=everything["next_cursor"]
    )
    assert [o["id"] for o in rest["items"]] == [dk.id] and rest["next_cursor"] is None

    elsewhere = await _get(db_client, search, q="Библиотека", locality_id=other.id)
    assert [o["name"] for o in elsewhere["items"]] == ["Библиотека семейного чтения"]

    r = await db_client.get(search, params={"type": "bank"})
    assert r.status_code == 422
    r = await db_client.get(search, params={"q": "%_%", "locality_id": locality.id})
    assert r.status_code == 200 and r.json()["items"] == []


async def test_demo_org_is_marked(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    locality = await _place(db_session, "Демково")
    seed = User(first_name="Демо-данные", username=SEED_USERNAME)
    db_session.add(seed)
    await db_session.flush()
    org = Organization(
        name="Демо-парк",
        kind=OrgKind.park,
        locality_id=locality.id,
        created_by=seed.id,
        description=org_description(OrgKind.park, "Демково"),
    )
    db_session.add(org)
    await db_session.commit()

    body = await _get(db_client, f"/api/v1/orgs/{org.id}/public")
    assert body["is_demo"] is True
    assert body["description"].startswith("Парк — Демково.")
    assert body["description"].endswith(ORG_NOTE)


def test_demo_description_is_deterministic() -> None:
    assert org_description("dk", "Кириллов") == org_description("dk", "Кириллов")
    assert org_description("unknown", "Кириллов").startswith("Организатор событий — Кириллов.")
