"""Демо-набор: валидность файлов, идемпотентная загрузка, пометка demo, соседние сёла,
городской слой Казани и Москвы."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.demo.generate import TARGET_EVENTS, build_city_events
from app.models.enums import EventStatus
from app.models.events import Event, EventSource
from app.models.geo import Locality
from app.models.system import AuditLog
from app.seed import SOURCE, SeedData, default_seed_dir, load, read_seed
from app.services.localities import geo_point
from tests.helpers import login

TZ = ZoneInfo("Europe/Moscow")
REGIONS = {"53", "16", "76", "77"}
CITIES = {"kazan": "Казань", "moscow": "Москва"}


def test_seed_files_are_valid() -> None:
    data = read_seed(default_seed_dir())
    assert len(data.localities) >= 30 and len(data.venues) >= 80
    assert {loc.region_code for loc in data.localities} == REGIONS
    orgs = [v for v in data.venues if v.org_kind is not None]
    assert len(orgs) >= 40 and any(not v.verified for v in orgs)
    assert len(data.events) == TARGET_EVENTS + len(build_city_events())
    region = {loc.key: loc.region_code for loc in data.localities}
    assert {region[e.locality] for e in data.events} == REGIONS
    official = [e for e in data.events if e.organizer == "venue"]
    assert official and len(official) < len(data.events)
    assert any(e.pushkin_card for e in official)
    assert not any(e.pushkin_card for e in data.events if e.organizer is None)
    assert {e.price_type for e in data.events} >= {"free", "paid"}
    days = [s.day for e in data.events for s in e.sessions]
    assert min(days) == 0 and 21 <= max(days) <= 28
    # События непроверенных организаций — только в ленте сообщества.
    unverified = {v.key for v in orgs if not v.verified}
    assert all(e.organizer is None for e in data.events if e.venue in unverified)


def test_city_events_cover_both_feeds() -> None:
    data = read_seed(default_seed_dir())
    venues = {v.key: v for v in data.venues}
    for city in CITIES:
        events = [e for e in data.events if e.key.startswith(f"demo-{city}-")]
        assert 15 <= len(events) <= 20
        places = {v.key for v in venues.values() if v.locality == city}
        assert 6 <= len({e.venue for e in events if e.venue}) <= len(places)
        official = [e for e in events if e.organizer == "venue"]
        community = [e for e in events if e.organizer is None]
        assert official and community
        assert all(venues[e.venue].verified for e in official if e.venue)
        assert len({e.category for e in events}) >= 8
        assert any(e.price_type == "free" for e in events)
        assert any(e.category == "kids" for e in events)
        assert any(e.pushkin_card for e in official)
        # Сегодня, завтра и любые ближайшие выходные — в обеих лентах; горизонт — 2 недели.
        for feed in (official, community):
            days = {s.day for e in feed for s in e.sessions}
            assert set(range(7)) <= days and max(days) <= 13


def test_seed_is_deterministic() -> None:
    first = read_seed(default_seed_dir()).events
    second = read_seed(default_seed_dir()).events
    assert [e.model_dump() for e in first] == [e.model_dump() for e in second]


async def _count(session: AsyncSession, stmt: Select[tuple[int]]) -> int:
    return await session.scalar(stmt) or 0


async def _novgorod(session: AsyncSession) -> Locality:
    locality = await session.scalar(select(Locality).where(Locality.name == "Великий Новгород"))
    assert locality is not None
    return locality


async def test_seed_idempotent_and_marked(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    data = read_seed(default_seed_dir())
    demo_sources = select(func.count()).select_from(EventSource).where(EventSource.source == SOURCE)
    loads = select(func.count()).select_from(AuditLog).where(AuditLog.action == "seed.demo_load")
    loads_before = await _count(db_session, loads)
    now = datetime.now(TZ)

    await load(db_session, data, now=now)
    assert await _count(db_session, demo_sources) == len(data.events)
    again = await load(db_session, data, now=now)
    assert again.created == {}
    assert again.updated == {}
    assert await _count(db_session, demo_sources) == len(data.events)
    assert await _count(db_session, loads) == loads_before + 2

    tiers = await db_session.scalars(
        select(Event.trust_tier)
        .join(EventSource, EventSource.event_id == Event.id)
        .where(EventSource.source == SOURCE)
        .distinct()
    )
    assert list(tiers) == ["demo"]

    params: dict[str, Any] = {
        "locality_id": (await _novgorod(db_session)).id,
        "tier": "all",
        "limit": 50,
    }
    near = (await db_client.get("/api/v1/events", params={**params, "radius_km": 5})).json()
    wide = (await db_client.get("/api/v1/events", params={**params, "radius_km": 15})).json()
    assert near["items"] and all(item["is_demo"] for item in near["items"])
    villages = {"Савино", "Ермолино"}
    assert not {item["locality"]["name"] for item in near["items"]} & villages
    # Радиус 15 км захватывает соседние сёла (Савино ~8 км, Ермолино ~7 км).
    assert {item["locality"]["name"] for item in wide["items"]} & villages

    official = await db_client.get("/api/v1/events", params={**params, "tier": "official"})
    community = await db_client.get("/api/v1/events", params={**params, "tier": "community"})
    assert official.json()["items"] and community.json()["items"]
    assert all(item["org"] is not None for item in official.json()["items"])
    assert all(item["org"] is None for item in community.json()["items"])


async def test_seed_reload_shifts_sessions_and_keeps_saved(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    data = read_seed(default_seed_dir())
    now = datetime.now(TZ)
    await load(db_session, data, now=now)
    headers, _ = await login(db_client)

    novgorod = await _novgorod(db_session)
    feed = await db_client.get(
        "/api/v1/events", params={"locality_id": novgorod.id, "tier": "all", "radius_km": 50}
    )
    card = feed.json()["items"][0]
    session_id = card["next_session"]["id"]
    saved = await db_client.post(
        f"/api/v1/events/{card['id']}/save", json={"session_id": session_id}, headers=headers
    )
    assert saved.status_code == 200, saved.text

    # Загрузка «завтра» сдвигает все сеансы на сутки, «Пойду» остаётся на том же сеансе.
    stats = await load(db_session, data, now=now + timedelta(days=1))
    assert stats.updated.get("events") == len(data.events)
    detail = (await db_client.get(f"/api/v1/events/{card['id']}", headers=headers)).json()
    assert detail["saved_session_ids"] == [session_id]
    shifted = next(s for s in detail["sessions"] if s["id"] == session_id)
    before = datetime.fromisoformat(card["next_session"]["starts_at"])
    assert datetime.fromisoformat(shifted["starts_at"]) - before == timedelta(days=1)


async def test_seed_archives_dropped_events(db_session: AsyncSession) -> None:
    data = read_seed(default_seed_dir())
    now = datetime.now(TZ)
    await load(db_session, data, now=now)
    dropped = data.events[-1]
    status = (
        select(Event.status)
        .join(EventSource, EventSource.event_id == Event.id)
        .where(EventSource.source == SOURCE, EventSource.source_id == dropped.key)
    )

    partial = SeedData(data.localities, data.venues, data.events[:-1])
    stats = await load(db_session, partial, now=now)
    assert stats.updated.get("archived") == 1
    assert await db_session.scalar(status) == EventStatus.archived

    await load(db_session, data, now=now)
    assert await db_session.scalar(status) == EventStatus.published


async def _all_items(client: httpx.AsyncClient, params: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page = await client.get(
            "/api/v1/events", params={**params, "cursor": cursor} if cursor else params
        )
        assert page.status_code == 200, page.text
        body = page.json()
        items += body["items"]
        cursor = body.get("next_cursor")
        if not cursor:
            return items


async def test_seed_cities_have_both_feeds_within_5km(
    db_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    data = read_seed(default_seed_dir())
    await load(db_session, data, now=datetime.now(TZ))
    for key, name in CITIES.items():
        seed = next(loc for loc in data.localities if loc.key == key)
        locality = await db_session.scalar(
            select(Locality)
            .where(Locality.name == name)
            .order_by(func.ST_Distance(Locality.point, geo_point(seed.lat, seed.lon)))
            .limit(1)
        )
        assert locality is not None
        titles = {
            tier: {
                e.title
                for e in data.events
                if e.key.startswith(f"demo-{key}-")
                and (e.organizer == "venue") == (tier == "official")
            }
            for tier in ("official", "community")
        }
        for tier, expected in titles.items():
            params = {"locality_id": locality.id, "tier": tier, "radius_km": 5, "limit": 50}
            items = await _all_items(db_client, params)
            assert expected <= {item["title"] for item in items}, (name, tier)
            assert all(item["is_demo"] for item in items)
            assert all((item["org"] is not None) == (tier == "official") for item in items)
