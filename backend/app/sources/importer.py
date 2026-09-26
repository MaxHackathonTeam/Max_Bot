"""Импорт источника с идемпотентным upsert и слиянием дублей."""

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.schemas import EnrichmentOut
from app.models.enums import AuditActor
from app.models.events import Event, EventSession, EventSource
from app.models.geo import Locality, Venue
from app.models.system import ImportRun
from app.services import audit
from app.services.categories import BY_SLUG
from app.services.localities import geo_point
from app.sources.base import EventSource as Source
from app.sources.base import RawEvent


async def _enrich(event: Event, llm: Any) -> None:
    if llm is None:
        return
    result = await llm.run_json(
        "event_enrich",
        "event_enrich",
        EnrichmentOut,
        categories=", ".join(BY_SLUG),
        title=event.title,
        description=event.description or "",
        category=event.category or "",
    )
    value = result.value if result.status == "ok" else None
    if value is None:
        return
    for field in ("category", "tags", "short_description", "indoor", "youth_score"):
        candidate = getattr(value, field)
        if candidate is None or field in (event.locked_fields or []):
            continue
        if getattr(event, field) in (None, [], "unknown") and (
            field != "category" or candidate in BY_SLUG
        ):
            setattr(event, field, candidate)
            event.ai_fields = sorted(set(event.ai_fields or []) | {field})


async def _duplicate(session: AsyncSession, item: RawEvent, locality_id: int) -> Event | None:
    if item.lat is None or item.lon is None:
        return None
    return cast(
        Event | None,
        await session.scalar(
            select(Event)
            .join(EventSession)
            .join(Venue)
            .where(
                Event.locality_id == locality_id,
                func.ST_DWithin(Venue.point, geo_point(item.lat, item.lon), 150),
                EventSession.starts_at.between(
                    item.starts_at - timedelta(minutes=30), item.starts_at + timedelta(minutes=30)
                ),
                func.similarity(Event.title, item.title) >= 0.6,
            )
            .limit(1)
        ),
    )


async def _one(session: AsyncSession, item: RawEvent, source: str, llm: Any = None) -> str:
    link = await session.scalar(
        select(EventSource).where(
            EventSource.source == source, EventSource.source_id == item.source_id
        )
    )
    if link:
        link.fetched_at = datetime.now(UTC)
        return "updated"
    locality = await session.scalar(
        select(Locality).where(func.lower(Locality.name) == (item.locality or "").lower())
    )
    if locality is None:
        return "skipped"
    event = await _duplicate(session, item, locality.id)
    venue = None
    if item.lat is not None and item.lon is not None:
        venue = await session.scalar(
            select(Venue)
            .where(
                Venue.locality_id == locality.id,
                func.ST_DWithin(Venue.point, geo_point(item.lat, item.lon), 150),
            )
            .limit(1)
        )
    if event is None:
        if venue is None and item.lat is not None and item.lon is not None:
            venue = Venue(
                name=item.venue_name[:255],
                address=item.address,
                locality_id=locality.id,
                point=geo_point(item.lat, item.lon),
                source=source,
            )
            session.add(venue)
            await session.flush()
        event = Event(
            title=item.title[:255],
            description=item.description,
            category=item.category if item.category in BY_SLUG else None,
            trust_tier="demo" if item.demo else "official",
            status="published",
            venue_id=venue.id if venue else None,
            locality_id=locality.id,
            pushkin_card=item.pushkin_card,
            price_type="paid" if item.price_min is not None else "unknown",
            price_min=item.price_min,
            ticket_url=item.ticket_url,
            locked_fields=[],
            ai_fields=[],
        )
        session.add(event)
        await session.flush()
        session.add(EventSession(event_id=event.id, starts_at=item.starts_at))
        await _enrich(event, llm)
        await audit.record(
            session,
            actor_type=AuditActor.system,
            action="import_create",
            entity_type="event",
            entity_id=event.id,
            diff={"source": source},
        )
        result = "created"
    else:
        result = "updated"
    session.add(
        EventSource(
            event_id=event.id,
            source=source,
            source_id=item.source_id,
            source_url=item.source_url,
            raw=item.raw,
        )
    )
    return result


async def run_import(
    session: AsyncSession, source: Source, region_codes: list[str], llm: Any = None
) -> dict[str, int]:
    run = ImportRun(source=source.code, started_at=datetime.now(UTC), stats={})
    session.add(run)
    stats = {"fetched": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
    async for item in source.fetch(region_codes, date.today(), date.today() + timedelta(days=60)):
        stats["fetched"] += 1
        try:
            stats[await _one(session, item, source.code, llm)] += 1
        except Exception:
            stats["errors"] += 1
    run.stats, run.finished_at = stats, datetime.now(UTC)
    await session.commit()
    return stats
