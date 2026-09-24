from datetime import datetime
from typing import Any

from sqlalchemy import REAL, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, enum_check
from app.models.enums import AuditActor, ModerationActor, ModerationVerdict


class ModerationDecision(IdMixin, TimestampMixin, Base):
    __tablename__ = "moderation_decisions"
    __table_args__ = (
        enum_check("actor_type", ModerationActor),
        enum_check("verdict", ModerationVerdict),
        Index("ix_moderation_decisions_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verdict: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float | None] = mapped_column(REAL)
    reasons: Mapped[Any] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))


class AuditLog(IdMixin, TimestampMixin, Base):
    """Только INSERT: UPDATE/DELETE запрещены правами роли и триггером (первая миграция)."""

    __tablename__ = "audit_log"
    __table_args__ = (
        enum_check("actor_type", AuditActor),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    actor_type: Mapped[str] = mapped_column(String(16))
    # Без FK: журнал переживает любые изменения пользователей.
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))


class ImportRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_runs"

    source: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class LlmCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_calls"

    purpose: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
