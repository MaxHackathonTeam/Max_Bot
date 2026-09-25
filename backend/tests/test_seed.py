"""Демо-набор: валидность файлов, идемпотентная загрузка, пометка demo, соседние сёла."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event, EventSource
from app.models.geo import Locality
from app.models.system import AuditLog
from app.seed import SOURCE, default_seed_dir, load, read_seed
from tests.helpers import login

TZ = ZoneInfo("Europe/Moscow")
TATARSTAN = {"kazan", "vysokaya_gora", "laishevo"}


def test_seed_files_are_valid() -> None:
    data = read_seed(default_seed_dir())
    novgorod = [e for e in data.events if e.locality not in TATARSTAN]
    # §7.2: 150–300 событий для демо-региона + несколько для Казани.
    assert 150 <= len(novgorod) <= 300
    assert len(data.events) > len(novgorod)
    assert any(e.organizer is None for e in data.events)
    assert any(e.organizer == "venue" for e in data.events)


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
