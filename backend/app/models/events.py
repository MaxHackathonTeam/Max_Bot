from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    REAL,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, enum_check
from app.models.enums import DraftOrigin, EventStatus, Indoor, PriceType, SessionStatus, TrustTier

SEARCH_TSV_EXPR = (
    "setweight(to_tsvector('russian', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('russian', coalesce(short_description, '')), 'B') || "
    "setweight(to_tsvector('russian', coalesce(description, '')), 'C')"
)


class Media(IdMixin, TimestampMixin, Base):
    __tablename__ = "media"

    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    mime: Mapped[str] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)


class Event(IdMixin, TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        enum_check("trust_tier", TrustTier),
        enum_check("status", EventStatus),
        enum_check("indoor", Indoor),
        enum_check("price_type", PriceType),
        Index("ix_events_status_trust_tier", "status", "trust_tier"),
        Index("ix_events_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_events_tags", "tags", postgresql_using="gin"),
        Index(
            "ix_events_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    short_description: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"), default=list)
    cover_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id"))
    cover_url: Mapped[str | None] = mapped_column(String(2048))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    trust_tier: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'draft'"), default=EventStatus.draft
    )
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.id"), index=True)
    locality_id: Mapped[int | None] = mapped_column(ForeignKey("localities.id"), index=True)
    is_online: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    online_url: Mapped[str | None] = mapped_column(String(2048))
    indoor: Mapped[str] = mapped_column(
        String(16), server_default=text("'unknown'"), default=Indoor.unknown
    )
    price_type: Mapped[str] = mapped_column(
        String(16), server_default=text("'unknown'"), default=PriceType.unknown
    )
    price_min: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_max: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    pushkin_card: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    age_rating: Mapped[int | None] = mapped_column(SmallInteger)
    youth_score: Mapped[float | None] = mapped_column(REAL)
    registration_required: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    ticket_url: Mapped[str | None] = mapped_column(String(2048))
    contacts: Mapped[str | None] = mapped_column(Text)
    accessibility: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    locked_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    ai_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed(SEARCH_TSV_EXPR, persisted=True)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "event_sessions"
    __table_args__ = (enum_check("status", SessionStatus),)

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'scheduled'"), default=SessionStatus.scheduled
    )


class EventSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "event_sources"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "event_drafts"
    __table_args__ = (enum_check("origin", DraftOrigin),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(String(16))
    ai_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "saved_sessions"
    __table_args__ = (UniqueConstraint("user_id", "session_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[int] = mapped_column(
        ForeignKey("event_sessions.id", ondelete="CASCADE"), index=True
    )
