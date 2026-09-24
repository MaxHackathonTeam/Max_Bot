from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, enum_check
from app.models.enums import NotificationStatus, ReportReason, SubscriptionKind


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        enum_check("kind", SubscriptionKind),
        # NULLS NOT DISTINCT: одна подписка на дайджест (org_id NULL) на пользователя.
        UniqueConstraint("user_id", "kind", "org_id", postgresql_nulls_not_distinct=True),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    org_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        enum_check("status", NotificationStatus),
        Index("ix_notifications_status_scheduled_at", "status", "scheduled_at"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'scheduled'"), default=NotificationStatus.scheduled
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Report(IdMixin, TimestampMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (enum_check("reason", ReportReason), UniqueConstraint("event_id", "user_id"))

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "analytics_events"
    __table_args__ = (Index("ix_analytics_events_name_created_at", "name", "created_at"),)

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(64))
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
