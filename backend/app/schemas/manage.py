"""Схемы управления событиями (FR-PUB) и администрирования (§6)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import Indoor, PriceType, ReportReason
from app.schemas.events import SessionOut, VenueBrief

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)]
AgeRating = Literal[0, 6, 12, 16, 18]


class Accessibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ramp: bool = False
    toilet: bool = False
    sign_language: bool = False


class SessionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(default=None, description="Существующий сеанс; без id — новый")
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None = None


class EventFields(BaseModel):
    """Поля формы. Лимиты длины и формата проверяются правилами при отправке (§6)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    short_description: str | None = Field(default=None, max_length=512)
    category: str | None = Field(default=None, max_length=32)
    tags: list[Tag] | None = Field(default=None, max_length=20)
    cover_media_id: int | None = None
    venue_id: int | None = None
    locality_id: int | None = None
    is_online: bool | None = None
    online_url: Url | None = None
    indoor: Indoor | None = None
    price_type: PriceType | None = None
    price_min: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    price_max: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    pushkin_card: bool | None = None
    age_rating: AgeRating | None = None
    registration_required: bool | None = None
    ticket_url: Url | None = None
    contacts: str | None = Field(default=None, max_length=500)
    accessibility: Accessibility | None = None
    sessions: list[SessionIn] | None = Field(default=None, max_length=50)


class EventCreate(EventFields):
    title: str = Field(min_length=1, max_length=255)
    organization_id: int | None = Field(
        default=None, description="От организации; без него — как автор сообщества"
    )


class EventPatch(EventFields):
    """Меняются только переданные поля; `sessions` заменяет список целиком."""


class EventManage(BaseModel):
    """Полное редактируемое представление события для автора и команды."""

    id: int
    status: str
    trust_tier: str
    organization_id: int | None
    org_name: str | None
    org_verified: bool
    author_user_id: int | None
    title: str
    description: str | None
    short_description: str | None
    category: str | None
    tags: list[str]
    cover_media_id: int | None
    cover_url: str | None
    venue: VenueBrief | None
    locality_id: int | None
    locality_name: str | None
    timezone: str
    is_online: bool
    online_url: str | None
    indoor: str
    price_type: str
    price_min: Decimal | None
    price_max: Decimal | None
    pushkin_card: bool
    age_rating: int | None
    registration_required: bool
    ticket_url: str | None
    contacts: str | None
    accessibility: dict[str, Any] | None
    sessions: list[SessionOut]
    locked_fields: list[str]
    ai_fields: list[str]
    moderation_reason: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    can_pushkin: bool = Field(description="Пушкинская карта доступна только проверенным")


class MyEventItem(BaseModel):
    id: int
    title: str
    status: str
    trust_tier: str
    category: str | None
    cover_url: str | None
    organization_id: int | None
    org_name: str | None
    next_starts_at: datetime | None
    timezone: str
    moderation_reason: str | None
    updated_at: datetime


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReportReason
    comment: str | None = Field(default=None, max_length=1000)


class ReportOut(BaseModel):
    accepted: bool = Field(description="False — жалоба от тебя на это событие уже есть")


class EventDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "hide"]
    reason: str | None = Field(default=None, max_length=1000)


class VerificationDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class RevokeOut(BaseModel):
    org_id: int
    events_moved: int


class QueueEvent(BaseModel):
    id: int
    title: str
    status: str
    trust_tier: str
    organization_id: int | None
    org_name: str | None
    moderation_reason: str | None
    reports: int
    next_starts_at: datetime | None
    updated_at: datetime


class QueueVerification(BaseModel):
    id: int
    org_id: int
    org_name: str
    method: str
    inn: str | None
    site_url: str | None
    steps: list[dict[str, Any]]
    created_at: datetime


class QueueOut(BaseModel):
    events: list[QueueEvent]
    verifications: list[QueueVerification]


class AuditItem(BaseModel):
    id: int
    created_at: datetime
    actor_type: str
    actor_user_id: int | None
    action: str
    entity_type: str
    entity_id: int | None
    diff: dict[str, Any] | None
    request_id: str | None


class AuditPage(BaseModel):
    items: list[AuditItem]
    next_before_id: int | None
