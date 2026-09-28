"""Черновик из сообщения: правила извлекают поля, автор проверяет их в обычной форме."""

from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import AuditActor, PriceType
from app.models.events import Event
from app.models.geo import Locality, Venue
from app.models.users import User
from app.parsing import extract
from app.schemas.manage import EventCreate, SessionIn
from app.services import audit, event_editor
from app.services.localities import DEFAULT_TIMEZONE

MIN_TEXT, MAX_TEXT = 10, 4000


def _https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def start_from_text(text: str, today: date, tz: ZoneInfo) -> datetime | None:
    """Первая явная дата + первое время после неё; только будущее."""
    dates = extract.find_explicit_dates(text, today)
    if not dates:
        return None
    day, (_, date_end) = dates[0]
    times = extract.find_times(text)
    after = [t for t, (start, _) in times if start >= date_end] or [t for t, _ in times]
    if not after:
        return None
    start = datetime.combine(day, after[0], tzinfo=tz)
    return start if start > datetime.now(tz) else None


async def _venue_by_address(
    session: AsyncSession, address: str, locality_id: int | None, org_id: int | None
) -> Venue | None:
    if locality_id is None:
        return None
    query = select(Venue).where(
        Venue.locality_id == locality_id,
        Venue.address.ilike(f"%{address}%"),
        or_(Venue.org_id.is_(None), Venue.org_id == org_id),
    )
    venue: Venue | None = await session.scalar(query.order_by(Venue.id).limit(1))
    return venue


async def create_from_text(
    session: AsyncSession, user: User, text: str, org_id: int | None
) -> Event:
    source = text.strip()
    if not MIN_TEXT <= len(source) <= MAX_TEXT:
        raise AppError("bad_text", "Текст анонса должен содержать от 10 до 4000 символов")
    locality = await session.get(Locality, user.locality_id) if user.locality_id else None
    tz = ZoneInfo(locality.timezone if locality and locality.timezone else DEFAULT_TIMEZONE)
    fields: dict[str, object] = {
        "title": extract.title_line(source),
        "description": source,
        "organization_id": org_id,
        "price_type": PriceType.unknown,
    }
    auto: list[str] = ["title"]

    categories = extract.find_categories(extract.tokenize(source))
    if categories.slugs:
        fields["category"] = categories.slugs[0]
        auto.append("category")
    price = extract.find_price(source)
    if price is not None:
        fields["price_type"] = PriceType(price.price_type)
        fields["price_min"] = price.price_min
        fields["price_max"] = price.price_max
        auto.append("price_type")
    if extract.find_pushkin(source):
        fields["pushkin_card"] = True
        auto.append("pushkin_card")
    ticket = next((url for url in extract.find_urls(source) if _https(url)), None)
    if ticket:
        fields["ticket_url"] = ticket
        auto.append("ticket_url")
    phone = extract.find_phone(source)
    if phone:
        fields["contacts"] = phone
        auto.append("contacts")
    start = start_from_text(source, datetime.now(tz).date(), tz)
    if start is not None:
        fields["sessions"] = [SessionIn(starts_at=start)]
        auto.append("sessions")
    address = extract.find_address(source)
    venue = await _venue_by_address(session, address, user.locality_id, org_id) if address else None
    if venue is not None:
        fields["venue_id"] = venue.id
        auto.append("venue_id")
    elif locality is not None:
        fields["locality_id"] = locality.id

    event = await event_editor.create(session, user, EventCreate.model_validate(fields))
    event.ai_fields = auto
    await audit.record(
        session,
        action="event.auto_fields",
        entity_type="event",
        entity_id=event.id,
        actor_type=AuditActor.system,
        diff={"fields": auto},
    )
    await session.commit()
    return event
