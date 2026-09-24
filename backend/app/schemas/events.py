from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class OrgBrief(BaseModel):
    id: int
    name: str
    verified: bool


class VenueBrief(BaseModel):
    id: int
    name: str
    address: str | None
    lat: float | None = None
    lon: float | None = None


class LocalityBrief(BaseModel):
    id: int
    name: str


class SessionOut(BaseModel):
    id: int
    starts_at: datetime
    ends_at: datetime | None
    status: str


class EventCard(BaseModel):
    """Элемент ленты: событие с ближайшим подходящим сеансом (FR-CAT-1)."""

    id: int
    title: str
    short_description: str | None
    category: str | None
    cover_url: str | None
    trust_tier: str
    is_demo: bool
    org: OrgBrief | None
    venue: VenueBrief | None
    locality: LocalityBrief | None
    timezone: str = Field(description="Часовой пояс населённого пункта события")
    next_session: SessionOut | None
    sessions_count: int
    distance_km: float | None
    price_type: str
    price_min: Decimal | None
    price_max: Decimal | None
    pushkin_card: bool
    age_rating: int | None
    is_online: bool


class EventPage(BaseModel):
    items: list[EventCard]
    next_cursor: str | None
    total: int | None = None


class SourceInfo(BaseModel):
    code: Literal["organizer", "community", "proculture", "demo"]
    label: str
    url: str | None
    updated_at: datetime


class EventDetail(EventCard):
    description: str | None
    tags: list[str]
    sessions: list[SessionOut]
    map_url: str | None
    online_url: str | None
    ticket_url: str | None
    registration_required: bool
    contacts: str | None
    accessibility: dict[str, Any] | None
    indoor: str
    source: SourceInfo
    ai_fields: list[str]
    status: str
    is_past: bool
    saved_session_ids: list[int] = Field(default_factory=list)
    share_url: str | None = Field(
        default=None, description="Диплинк https://max.ru/<бот>?startapp=ev_<id> для шеринга"
    )


class SaveIn(BaseModel):
    session_id: int | None = Field(
        default=None, description="Сеанс; по умолчанию — ближайший будущий"
    )


class SavedItem(BaseModel):
    session: SessionOut
    event: EventCard


class SaveOut(BaseModel):
    saved_session_ids: list[int]
