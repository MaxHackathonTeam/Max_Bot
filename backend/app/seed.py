"""Загрузка демо-набора: `python -m app.seed` (§7.1, §7.2).

Сначала — справочник НП России (app.seed_localities, всегда), затем демо (SEED_DEMO=1).

Населённые пункты и площадки — реальные, из data/seed/*.json (cities.json — отдельный слой
Казани и Москвы); события генерирует app.demo.generate (фиксированный seed). Все события —
`trust_tier=demo`, источник `demo` в `event_sources`, в ленте с плашкой. Загрузка
идемпотентна: события находятся по (source, source_id), сеансы обновляются на месте. Даты
относительные (`day` от сегодня в поясе населённого пункта), поэтому повторный запуск
сдвигает их к текущей дате. Статус события (например, скрытие модерацией) и поля из
`locked_fields` загрузка не меняет; демо-события, которых больше нет в наборе, уходят в
архив.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app import seed_localities
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import make_sessionmaker
from app.demo.generate import build_city_events, build_events
from app.demo.orgs import SEED_USERNAME, org_description
from app.models.enums import (
    AuditActor,
    EventStatus,
    Indoor,
    LocalityKind,
    OrgKind,
    PriceType,
    SessionStatus,
    TrustTier,
    VerificationMethod,
    VerificationStatus,
)
from app.models.events import Event, EventSession, EventSource
from app.models.geo import Locality, Venue
from app.models.orgs import Organization
from app.models.users import User
from app.services import audit
from app.services.categories import is_known
from app.services.localities import (
    SAME_NAME_M,
    geo_point,
    normalize,
    timezone_for,
    wkt_point,
)

SOURCE = "demo"

log = structlog.get_logger(__name__)


class LocalitySeed(BaseModel):
    key: str
    name: str
    kind: LocalityKind
    region: str
    region_code: str
    municipality: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    population: int | None = None


class VenueSeed(BaseModel):
    key: str
    locality: str
    name: str
    address: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    org_kind: OrgKind | None = None
    # Организация прошла проверку: её события идут в официальную ленту.
    verified: bool = True


class SessionSeed(BaseModel):
    day: int
    time: time
    duration_min: int = Field(gt=0)


class EventSeed(BaseModel):
    key: str
    title: str
    short_description: str | None = None
    description: str | None = None
    category: str
    tags: list[str] = []
    locality: str
    venue: str | None = None
    organizer: Literal["venue"] | None = None
    price_type: PriceType
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    pushkin_card: bool = False
    age_rating: int | None = None
    indoor: Indoor = Indoor.unknown
    registration_required: bool = False
    sessions: list[SessionSeed] = Field(min_length=1)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if not is_known(value):
            raise ValueError(f"неизвестная категория {value!r}")
        return value


@dataclass
class SeedData:
    localities: list[LocalitySeed]
    venues: list[VenueSeed]
    events: list[EventSeed]


@dataclass
class SeedStats:
    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, entity: str) -> None:
        bucket = self.created if kind == "created" else self.updated
        bucket[entity] = bucket.get(entity, 0) + 1


def default_seed_dir() -> Path:
    """В контейнере data/ лежит рядом с app/, локально — в корне репозитория."""
    here = Path(__file__).resolve()
    for base in (here.parents[1], here.parents[2]):
        candidate = base / "data" / "seed"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Не найден каталог data/seed")


def read_seed(seed_dir: Path) -> SeedData:
    def load(name: str) -> list[Any]:
        items = json.loads((seed_dir / name).read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError(f"{name}: ожидается список")
        return items

    raw_localities, raw_venues = load("localities.json"), load("venues.json")
    cities = json.loads((seed_dir / "cities.json").read_text(encoding="utf-8"))
    events = build_events(raw_localities, raw_venues) + build_city_events()
    data = SeedData(
        localities=[
            LocalitySeed.model_validate(x) for x in [*raw_localities, *cities["localities"]]
        ],
        venues=[VenueSeed.model_validate(x) for x in [*raw_venues, *cities["venues"]]],
        events=[EventSeed.model_validate(x) for x in events],
    )
    locality_keys = {loc.key for loc in data.localities}
    venue_keys = {v.key: v for v in data.venues}
    for venue in data.venues:
        if venue.locality not in locality_keys:
            raise ValueError(f"площадка {venue.key}: нет населённого пункта {venue.locality}")
    for event in data.events:
        if event.locality not in locality_keys:
            raise ValueError(f"событие {event.key}: нет населённого пункта {event.locality}")
        if event.venue is not None and event.venue not in venue_keys:
            raise ValueError(f"событие {event.key}: нет площадки {event.venue}")
        if event.organizer == "venue" and (
            event.venue is None
            or venue_keys[event.venue].org_kind is None
            or not venue_keys[event.venue].verified
        ):
            raise ValueError(f"событие {event.key}: у площадки нет проверенной организации")
    for kind, keys in (
        ("населённых пунктов", [x.key for x in data.localities]),
        ("площадок", [x.key for x in data.venues]),
        ("событий", [x.key for x in data.events]),
    ):
        if len(keys) != len(set(keys)):
            raise ValueError(f"повторяющиеся ключи {kind}")
    return data


class _Loader:
    def __init__(self, session: AsyncSession, today: date | None, now: datetime) -> None:
        self.session = session
        self.today = today
        self.now = now
        self.stats = SeedStats()
        self.user: User
        self.localities: dict[str, Locality] = {}
        self.venues: dict[str, Venue] = {}
        self.orgs: dict[str, Organization] = {}

    async def audit(
        self, action: str, entity_type: str, entity_id: int, diff: dict[str, Any] | None = None
    ) -> None:
        await audit.record(
            self.session,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_type=AuditActor.system,
            diff=diff,
        )

    async def seed_user(self) -> None:
        user = await self.session.scalar(
            select(User).where(User.username == SEED_USERNAME, User.max_user_id.is_(None))
        )
        if user is None:
            user = User(first_name="Демо-данные", username=SEED_USERNAME)
            self.session.add(user)
            await self.session.flush()
            await self.audit("user.create", "user", user.id, {"username": SEED_USERNAME})
            self.stats.add("created", "users")
        self.user = user

    async def locality(self, item: LocalitySeed) -> None:
        point = geo_point(item.lat, item.lon)
        # Уже есть (справочник НП или прошлая загрузка) — берём как есть. Правило то же,
        # что при привязке в app.seed_localities: точное имя или «имя …», ближайший.
        norm = normalize(item.name)
        exact = Locality.name_norm == norm
        found = await self.session.scalar(
            select(Locality)
            .where(
                exact | Locality.name_norm.like(norm + " %"),
                func.ST_DWithin(Locality.point, point, SAME_NAME_M),
            )
            .order_by(desc(exact), func.ST_Distance(Locality.point, point))
            .limit(1)
        )
        if found is None:
            found = Locality(
                name=item.name,
                kind=item.kind,
                region=item.region,
                region_code=item.region_code,
                municipality=item.municipality,
                point=wkt_point(item.lat, item.lon),
                timezone=timezone_for(item.lat, item.lon),
                population=item.population,
                source=SOURCE,
            )
            self.session.add(found)
            await self.session.flush()
            await self.audit("locality.create", "locality", found.id, {"source": SOURCE})
            self.stats.add("created", "localities")
        self.localities[item.key] = found

    async def venue(self, item: VenueSeed) -> None:
        locality = self.localities[item.locality]
        org: Organization | None = None
        if item.org_kind is not None:
            org = await self.session.scalar(
                select(Organization).where(
                    Organization.name == item.name, Organization.created_by == self.user.id
                )
            )
            status = VerificationStatus.verified if item.verified else VerificationStatus.unverified
            description = org_description(item.org_kind, locality.name)
            if org is None:
                org = Organization(
                    name=item.name,
                    kind=item.org_kind,
                    locality_id=locality.id,
                    address=item.address,
                    description=description,
                    created_by=self.user.id,
                )
                self.session.add(org)
                self._set_verification(org, status)
                await self.session.flush()
                await self.audit("org.create", "organization", org.id, {"source": SOURCE})
                self.stats.add("created", "organizations")
            elif org.verification_status != status:
                old = org.verification_status
                self._set_verification(org, status)
                await self.audit(
                    "org.update", "organization", org.id, {"verification_status": [old, status]}
                )
                self.stats.add("updated", "organizations")
            if org.description != description:
                org.description = description
                await self.audit("org.update", "organization", org.id, {"fields": ["description"]})
                self.stats.add("updated", "organizations")
            self.orgs[item.key] = org
        venue = await self.session.scalar(
            select(Venue).where(
                Venue.name == item.name, Venue.locality_id == locality.id, Venue.source == SOURCE
            )
        )
        if venue is None:
            venue = Venue(
                name=item.name,
                address=item.address,
                locality_id=locality.id,
                point=wkt_point(item.lat, item.lon),
                org_id=org.id if org else None,
                source=SOURCE,
            )
            self.session.add(venue)
            await self.session.flush()
            await self.audit("venue.create", "venue", venue.id, {"source": SOURCE})
            self.stats.add("created", "venues")
        self.venues[item.key] = venue

    def _set_verification(self, org: Organization, status: VerificationStatus) -> None:
        verified = status == VerificationStatus.verified
        org.verification_status = status
        org.verification_method = VerificationMethod.manual if verified else None
        org.verified_at = self.now if verified else None

    async def archive_stale(self, keys: set[str]) -> None:
        """Демо-события, выпавшие из набора, — в архив (не удаляем: на них могут быть «Пойду»)."""
        rows = await self.session.execute(
            select(Event, EventSource.source_id)
            .join(EventSource, EventSource.event_id == Event.id)
            .where(EventSource.source == SOURCE, Event.status != EventStatus.archived)
        )
        for event, key in rows.tuples():
            if key in keys:
                continue
            old = event.status
            event.status = EventStatus.archived
            await self.audit("event.archive", "event", event.id, {"status": [old, "archived"]})
            self.stats.add("updated", "archived")

    def _fields(self, item: EventSeed) -> dict[str, Any]:
        venue = self.venues[item.venue] if item.venue else None
        org = self.orgs[item.venue] if item.organizer == "venue" and item.venue else None
        return {
            "title": item.title,
            "short_description": item.short_description,
            "description": item.description,
            "category": item.category,
            "tags": item.tags,
            "locality_id": self.localities[item.locality].id,
            "venue_id": venue.id if venue else None,
            "organization_id": org.id if org else None,
            "price_type": item.price_type,
            "price_min": item.price_min,
            "price_max": item.price_max,
            "pushkin_card": item.pushkin_card,
            "age_rating": item.age_rating,
            "indoor": item.indoor,
            "registration_required": item.registration_required,
        }

    def _sessions(self, item: EventSeed) -> list[tuple[datetime, datetime]]:
        tz = ZoneInfo(self.localities[item.locality].timezone)
        today = self.today or self.now.astimezone(tz).date()
        result = []
        for s in item.sessions:
            starts = datetime.combine(today + timedelta(days=s.day), s.time, tzinfo=tz)
            result.append((starts, starts + timedelta(minutes=s.duration_min)))
        return result

    async def event(self, item: EventSeed) -> None:
        source = await self.session.scalar(
            select(EventSource).where(
                EventSource.source == SOURCE, EventSource.source_id == item.key
            )
        )
        fields = self._fields(item)
        event = await self.session.get(Event, source.event_id) if source else None
        if event is None:
            event = Event(
                **fields,
                trust_tier=TrustTier.demo,
                status=EventStatus.published,
                author_user_id=self.user.id,
                published_at=self.now,
            )
            self.session.add(event)
            await self.session.flush()
            if source is None:
                self.session.add(
                    EventSource(
                        event_id=event.id, source=SOURCE, source_id=item.key, raw={"key": item.key}
                    )
                )
            else:
                source.event_id = event.id
            await self.audit("event.create", "event", event.id, {"source": SOURCE, "key": item.key})
            await self._sync_sessions(event, item)
            self.stats.add("created", "events")
            return
        changed = {
            name: [_plain(getattr(event, name)), _plain(value)]
            for name, value in fields.items()
            if name not in event.locked_fields and getattr(event, name) != value
        }
        for name in changed:
            setattr(event, name, fields[name])
        if event.status == EventStatus.archived:
            # Вернулось в набор после archive_stale.
            event.status = EventStatus.published
            changed["status"] = ["archived", "published"]
        sessions_changed = await self._sync_sessions(event, item)
        if changed or sessions_changed:
            if sessions_changed:
                changed["sessions"] = ["сдвинуты", "к текущей дате"]
            await self.audit("event.update", "event", event.id, changed)
            self.stats.add("updated", "events")

    async def _sync_sessions(self, event: Event, item: EventSeed) -> bool:
        """Сеансы обновляются на месте, чтобы не терять «Пойду» при повторной загрузке."""
        wanted = self._sessions(item)
        existing = list(
            await self.session.scalars(
                select(EventSession)
                .where(EventSession.event_id == event.id)
                .order_by(EventSession.starts_at, EventSession.id)
            )
        )
        changed = False
        for current, (starts, ends) in zip(existing, wanted, strict=False):
            if (current.starts_at, current.ends_at, current.status) != (
                starts,
                ends,
                SessionStatus.scheduled,
            ):
                current.starts_at, current.ends_at = starts, ends
                current.status = SessionStatus.scheduled
                changed = True
        for starts, ends in wanted[len(existing) :]:
            self.session.add(EventSession(event_id=event.id, starts_at=starts, ends_at=ends))
            changed = True
        for extra in existing[len(wanted) :]:
            await self.session.delete(extra)
            changed = True
        await self.session.flush()
        return changed


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


async def load(
    session: AsyncSession,
    data: SeedData,
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> SeedStats:
    """Загружает набор в одной транзакции. `today` — для тестов (иначе — сегодня в поясе НП)."""
    loader = _Loader(session, today, now or datetime.now().astimezone())
    await loader.seed_user()
    for loc in data.localities:
        await loader.locality(loc)
    for venue in data.venues:
        await loader.venue(venue)
    for event in data.events:
        await loader.event(event)
    await loader.archive_stale({e.key for e in data.events})
    await audit.record(
        session,
        action="seed.demo_load",
        entity_type="seed",
        entity_id=None,
        actor_type=AuditActor.system,
        diff={"created": loader.stats.created, "updated": loader.stats.updated},
    )
    await session.commit()
    return loader.stats


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    seed_dir = default_seed_dir()
    engine = create_async_engine(settings.alembic_database_url)
    try:
        # Справочник НП — реальные данные, грузится всегда (повторно — только при новом файле).
        async with make_sessionmaker(engine)() as session:
            await seed_localities.load(session, seed_dir / seed_localities.FILE_NAME)
            await session.commit()
        if not settings.seed_demo:
            log.info("seed_skipped", reason="SEED_DEMO=0")
            return
        data = read_seed(seed_dir)
        async with make_sessionmaker(engine)() as session:
            stats = await load(session, data)
    finally:
        await engine.dispose()
    log.info("seed_loaded", created=stats.created, updated=stats.updated)


if __name__ == "__main__":
    asyncio.run(main())
