"""GET /events, GET /events/{id}, «Пойду» — с настоящей БД (TEST_DATABASE_URL)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventStatus, TrustTier
from app.models.system import AuditLog
from app.services import events as events_service
from app.services.events import EventFilters
from tests.factories import (
    in_hours,
    make_event,
    make_locality,
    make_org,
    make_venue,
    random_area,
    shift_north,
)
from tests.helpers import login


async def _feed(client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    r = await client.get("/api/v1/events", params=params)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def _titles(body: dict[str, Any]) -> list[str]:
    return [item["title"] for item in body["items"]]


async def _all_pages(client: httpx.AsyncClient, **params: Any) -> tuple[list[str], int]:
    seen: list[str] = []
    pages = 0
    cursor = None
    while True:
        body = await _feed(client, **params, **({"cursor": cursor} if cursor else {}))
        seen += _titles(body)
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            return seen, pages


async def test_radius_includes_neighbour_villages(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Райцентр", lat, lon, kind="town")
    near = await make_locality(db_session, "Соседнее", *shift_north(lat, lon, 12))
    far = await make_locality(db_session, "Дальнее", *shift_north(lat, lon, 40))
    await make_event(db_session, town, title="В райцентре", starts=[in_hours(5)])
    venue = await make_venue(db_session, near, *shift_north(lat, lon, 12.2))
    await make_event(db_session, near, venue=venue, title="В соседнем селе", starts=[in_hours(4)])
    await make_event(db_session, far, title="В дальнем селе", starts=[in_hours(3)])
    await db_session.commit()

    body = await _feed(db_client, locality_id=town.id, radius_km=15)
    assert _titles(body) == ["В соседнем селе", "В райцентре"]
    near_card = body["items"][0]
    assert near_card["locality"]["name"] == "Соседнее"
    assert 11.5 < near_card["distance_km"] < 13
    assert near_card["venue"]["address"].startswith("Соседнее")

    body = await _feed(db_client, locality_id=town.id, radius_km=5)
    assert _titles(body) == ["В райцентре"]

    body = await _feed(db_client, locality_id=town.id, radius_km=50, sort="distance")
    assert _titles(body) == ["В райцентре", "В соседнем селе", "В дальнем селе"]

    lat_far, lon_far = shift_north(lat, lon, 40)
    body = await _feed(db_client, lat=lat_far, lon=lon_far, radius_km=5)
    assert _titles(body) == ["В дальнем селе"]


async def test_tiers_are_not_mixed_and_demo_is_marked(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Город", lat, lon)
    org = await make_org(db_session)
    await make_event(db_session, town, title="Офиц", org=org, trust_tier=TrustTier.official)
    await make_event(db_session, town, title="Сообщество", trust_tier=TrustTier.community)
    await make_event(db_session, town, title="Демо орг", org=org, trust_tier=TrustTier.demo)
    await make_event(db_session, town, title="Демо житель", trust_tier=TrustTier.demo)
    await db_session.commit()

    official = await _feed(db_client, locality_id=town.id)
    assert sorted(_titles(official)) == ["Демо орг", "Офиц"]
    by_title = {i["title"]: i for i in official["items"]}
    assert by_title["Демо орг"]["is_demo"] is True
    assert by_title["Офиц"]["is_demo"] is False
    assert by_title["Офиц"]["org"] == {"id": org.id, "name": org.name, "verified": True}

    community = await _feed(db_client, locality_id=town.id, tier="community")
    assert sorted(_titles(community)) == ["Демо житель", "Сообщество"]

    everything = await _feed(db_client, locality_id=town.id, tier="all", include_total=True)
    assert everything["total"] == 4


async def test_filters(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Посёлок", lat, lon)
    await make_event(db_session, town, title="Бесплатный концерт", category="concert")
    await make_event(
        db_session,
        town,
        title="Спектакль 300",
        category="theatre",
        price_type="paid",
        price_min=Decimal(300),
        pushkin_card=True,
        age_rating=12,
    )
    await make_event(
        db_session,
        town,
        title="Кино 800",
        category="cinema",
        price_type="paid",
        price_min=Decimal(800),
        age_rating=18,
    )
    await make_event(db_session, town, title="Онлайн-лекция", category="lecture", is_online=True)
    await make_event(db_session, town, title="Черновик", status=EventStatus.draft)
    await db_session.commit()
    base = {"locality_id": town.id}

    assert sorted(_titles(await _feed(db_client, **base, category=["theatre", "cinema"]))) == [
        "Кино 800",
        "Спектакль 300",
    ]
    assert sorted(_titles(await _feed(db_client, **base, free=True))) == [
        "Бесплатный концерт",
        "Онлайн-лекция",
    ]
    assert "Кино 800" not in _titles(await _feed(db_client, **base, price_max=500))
    assert "Спектакль 300" in _titles(await _feed(db_client, **base, price_max=500))
    assert _titles(await _feed(db_client, **base, pushkin=True)) == ["Спектакль 300"]
    assert "Кино 800" not in _titles(await _feed(db_client, **base, age=16))
    assert _titles(await _feed(db_client, **base, format="online")) == ["Онлайн-лекция"]
    assert "Онлайн-лекция" not in _titles(await _feed(db_client, **base, format="offline"))
    assert "Черновик" not in _titles(await _feed(db_client, **base, tier="all"))


async def test_text_search_fts_and_typos(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Село", lat, lon)
    await make_event(
        db_session, town, title="Концерт народного хора", short_description="Песни и частушки"
    )
    await make_event(db_session, town, title="Мастер-класс по гончарному делу")
    await db_session.commit()

    async def found(q: str) -> list[str]:
        return _titles(await _feed(db_client, locality_id=town.id, q=q))

    assert await found("концерты") == ["Концерт народного хора"]
    assert await found("частушки") == ["Концерт народного хора"]
    assert await found("гончарный") == ["Мастер-класс по гончарному делу"]
    # Опечатка ловится триграммами.
    assert await found("канцерт") == ["Концерт народного хора"]


async def test_past_sessions_hidden_next_session_grouped(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Деревня", lat, lon)
    past = await make_event(db_session, town, title="Прошло", starts=[in_hours(-30)])
    series = await make_event(
        db_session, town, title="Серия", starts=[in_hours(-2), in_hours(50), in_hours(26)]
    )
    await db_session.commit()

    body = await _feed(db_client, locality_id=town.id)
    assert _titles(body) == ["Серия"]
    card = body["items"][0]
    assert card["sessions_count"] == 2
    starts = datetime.fromisoformat(card["next_session"]["starts_at"])
    assert timedelta(hours=25) < starts - datetime.now(UTC) < timedelta(hours=27)

    r = await db_client.get(f"/api/v1/events/{past.id}")
    assert r.status_code == 200
    assert r.json()["is_past"] is True

    detail = (await db_client.get(f"/api/v1/events/{series.id}")).json()
    assert detail["is_past"] is False
    assert len(detail["sessions"]) == 2
    assert detail["map_url"].startswith("https://yandex.ru/maps/?pt=")
    assert detail["source"]["code"] == "organizer"
    assert detail["share_url"] == f"https://max.ru/afisha_test_bot?startapp=ev_{series.id}"


async def test_detail_hides_drafts(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Хутор", lat, lon)
    draft = await make_event(db_session, town, status=EventStatus.draft)
    demo = await make_event(db_session, town, trust_tier=TrustTier.demo)
    await db_session.commit()

    r = await db_client.get(f"/api/v1/events/{draft.id}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "event_not_found"
    source = (await db_client.get(f"/api/v1/events/{demo.id}")).json()["source"]
    assert (source["code"], source["label"]) == ("demo", "Демо-данные")


async def test_cursor_pagination(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Станция", lat, lon)
    same_time = in_hours(10)
    for i in range(25):
        # Часть событий в одно время и в одном месте — курсор различает их по id.
        starts = same_time if i % 3 == 0 else in_hours(1 + i)
        await make_event(db_session, town, title=f"Встреча {i:02d}", starts=[starts])
    await db_session.commit()

    for extra in ({}, {"sort": "distance"}, {"q": "встреча"}):
        seen, pages = await _all_pages(db_client, locality_id=town.id, limit=10, **extra)
        assert pages == 3, extra
        assert len(seen) == 25 == len(set(seen)), extra

    r = await db_client.get("/api/v1/events", params={"cursor": "мусор"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_cursor"


async def test_date_presets_use_locality_timezone(db_session: AsyncSession) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Восток", lat, lon, timezone="Asia/Vladivostok")
    # «Сейчас» — среда 12:00 по Владивостоку (UTC+10).
    now = datetime(2026, 9, 23, 2, 0, tzinfo=UTC)

    def at(day: int, hour: int) -> datetime:
        return datetime(2026, 9, day, hour, 0, tzinfo=UTC)

    await make_event(db_session, town, title="Сегодня вечером", starts=[at(23, 9)])
    await make_event(db_session, town, title="Завтра утром", starts=[at(23, 23)])
    await make_event(db_session, town, title="Суббота", starts=[at(26, 5)])
    await make_event(db_session, town, title="Понедельник", starts=[at(28, 5)])
    await db_session.commit()

    async def titles(**kwargs: Any) -> list[str]:
        page = await events_service.search(
            db_session, EventFilters(locality_id=town.id, **kwargs), now=now
        )
        return [c.title for c in page.items]

    assert await titles(date_preset="today") == ["Сегодня вечером"]
    assert await titles(date_preset="tomorrow") == ["Завтра утром"]
    assert await titles(date_preset="weekend") == ["Суббота"]
    assert await titles() == ["Сегодня вечером", "Завтра утром", "Суббота", "Понедельник"]


async def test_save_flow(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    lat, lon = random_area()
    town = await make_locality(db_session, "Слобода", lat, lon)
    event = await make_event(db_session, town, starts=[in_hours(30), in_hours(5)])
    await db_session.commit()

    headers, _ = await login(db_client, consents=False)
    r = await db_client.post(f"/api/v1/events/{event.id}/save", headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "consent_required"

    headers, _ = await login(db_client)
    r = await db_client.post(f"/api/v1/events/{event.id}/save", headers=headers)
    assert r.status_code == 200, r.text
    ids = r.json()["saved_session_ids"]
    assert len(ids) == 1
    r = await db_client.post(f"/api/v1/events/{event.id}/save", headers=headers, json={})
    assert r.json()["saved_session_ids"] == ids

    detail = (await db_client.get(f"/api/v1/events/{event.id}", headers=headers)).json()
    assert detail["saved_session_ids"] == ids
    assert detail["sessions"][0]["id"] == ids[0]  # по умолчанию — ближайший сеанс
    other = detail["sessions"][1]["id"]
    r = await db_client.post(
        f"/api/v1/events/{event.id}/save", headers=headers, json={"session_id": other}
    )
    assert sorted(r.json()["saved_session_ids"]) == sorted([*ids, other])

    saved = (await db_client.get("/api/v1/me/saved", headers=headers)).json()
    assert [s["session"]["id"] for s in saved] == [ids[0], other]
    assert saved[0]["event"]["id"] == event.id

    r = await db_client.delete(
        f"/api/v1/events/{event.id}/save", headers=headers, params={"session_id": other}
    )
    assert r.json()["saved_session_ids"] == ids
    r = await db_client.delete(f"/api/v1/events/{event.id}/save", headers=headers)
    assert r.json()["saved_session_ids"] == []

    actions = list(
        await db_session.scalars(
            select(AuditLog.action)
            .where(AuditLog.entity_type == "event", AuditLog.entity_id == event.id)
            .order_by(AuditLog.id)
        )
    )
    assert actions == ["event.save", "event.save", "event.unsave", "event.unsave"]

    r = await db_client.post(
        f"/api/v1/events/{event.id}/save", headers=headers, json={"session_id": 10**9}
    )
    assert r.status_code == 409
