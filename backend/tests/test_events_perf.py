"""Производительность ленты (§15): GET /events p95 < 300 мс при 10 000 событий."""

import statistics
import time
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_locality

EVENTS = 10_000
LOCALITIES = 40
# Отдельная область, не пересекается с random_area() других тестов.
CENTER_LAT, CENTER_LON = 50.0, 80.0
P95_LIMIT_MS = 300


async def _seed(session: AsyncSession) -> list[int]:
    ids = []
    for i in range(LOCALITIES):
        lat = CENTER_LAT + (i % 8) * 0.12
        lon = CENTER_LON + (i // 8) * 0.18
        ids.append((await make_locality(session, f"Перф-{i}", lat, lon)).id)
    await session.execute(
        text(
            """
            INSERT INTO events (title, short_description, description, category, trust_tier,
                                status, locality_id, price_type, price_min, pushkin_card,
                                age_rating, is_online, published_at)
            SELECT
                (ARRAY['Концерт', 'Спектакль', 'Выставка', 'Мастер-класс', 'Лекция'])[1 + g % 5]
                    || ' №' || g,
                'Короткое описание события ' || g,
                'Подробное описание: музыка, песни, народное творчество, встреча ' || g,
                (ARRAY['concert', 'theatre', 'exhibition', 'masterclass', 'lecture'])[1 + g % 5],
                (ARRAY['official', 'community', 'demo'])[1 + g % 3],
                'published',
                (CAST(:ids AS bigint[]))[1 + g % :n],
                (ARRAY['free', 'paid', 'donation'])[1 + g % 3],
                (g % 7) * 100,
                g % 4 = 0,
                (ARRAY[0, 6, 12, 16, 18])[1 + g % 5],
                g % 25 = 0,
                now()
            FROM generate_series(1, :events) AS g
            """
        ),
        {"ids": ids, "n": len(ids), "events": EVENTS},
    )
    await session.execute(
        text(
            """
            INSERT INTO event_sessions (event_id, starts_at, status)
            SELECT e.id,
                   now() + make_interval(hours => CAST((e.id * 7 + s * 53) % 720 - 24 AS int)),
                   'scheduled'
            FROM events e
            JOIN generate_series(0, 2) AS s ON s <= e.id % 3
            WHERE e.locality_id = ANY(CAST(:ids AS bigint[]))
            """
        ),
        {"ids": ids},
    )
    await session.commit()
    # В проде статистику обновит autovacuum; здесь без неё планировщик работает вслепую.
    for table in ("events", "event_sessions", "localities"):
        await session.execute(text(f"ANALYZE {table}"))
    return ids


async def test_events_feed_p95(db_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    ids = await _seed(db_session)
    center = ids[len(ids) // 2]
    scenarios: list[dict[str, Any]] = [
        {"locality_id": center, "radius_km": 30},
        {"locality_id": center, "radius_km": 50, "tier": "all"},
        {"locality_id": center, "radius_km": 50, "date": "weekend"},
        {"locality_id": center, "radius_km": 15, "date": "today"},
        {"locality_id": center, "radius_km": 50, "category": ["concert", "theatre"]},
        {"locality_id": center, "radius_km": 50, "free": True, "pushkin": True},
        {"locality_id": center, "radius_km": 50, "q": "концерт"},
        {"locality_id": center, "radius_km": 50, "q": "канцерт"},
        {"locality_id": center, "radius_km": 50, "sort": "distance"},
        {"lat": CENTER_LAT + 0.3, "lon": CENTER_LON + 0.3, "radius_km": 30, "tier": "community"},
    ]
    # Прогрев: планы запросов, пул соединений.
    for params in scenarios:
        assert (await db_client.get("/api/v1/events", params=params)).status_code == 200

    timings_ms: list[float] = []
    slowest: dict[int, float] = {}
    cursors = 0
    for _ in range(4):
        for i, params in enumerate(scenarios):
            started = time.perf_counter()
            r = await db_client.get("/api/v1/events", params=params)
            timings_ms.append((time.perf_counter() - started) * 1000)
            slowest[i] = max(slowest.get(i, 0.0), timings_ms[-1])
            assert r.status_code == 200, r.text
            body = r.json()
            if body["next_cursor"]:
                cursors += 1
                started = time.perf_counter()
                r = await db_client.get(
                    "/api/v1/events", params={**params, "cursor": body["next_cursor"]}
                )
                timings_ms.append((time.perf_counter() - started) * 1000)
                assert r.status_code == 200, r.text

    assert cursors > 0
    p95 = statistics.quantiles(timings_ms, n=20)[-1]
    median = statistics.median(timings_ms)
    print(f"GET /events: n={len(timings_ms)} p50={median:.1f} мс p95={p95:.1f} мс")
    for i, ms in sorted(slowest.items(), key=lambda kv: -kv[1])[:3]:
        print(f"  медленный сценарий {scenarios[i]}: {ms:.1f} мс")
    assert p95 < P95_LIMIT_MS
