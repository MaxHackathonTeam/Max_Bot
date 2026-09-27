from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, enum_check
from app.models.enums import OrgKind, OrgRole, VerificationMethod, VerificationStatus


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        enum_check("kind", OrgKind),
        enum_check("verification_status", VerificationStatus),
        enum_check("verification_method", VerificationMethod),
    )

    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    inn: Mapped[str | None] = mapped_column(String(12), index=True)
    ogrn: Mapped[str | None] = mapped_column(String(15))
    registry_name: Mapped[str | None] = mapped_column(Text)
    registry_status: Mapped[str | None] = mapped_column(String(32))
    locality_id: Mapped[int | None] = mapped_column(ForeignKey("localities.id"))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(2048))
    vk_url: Mapped[str | None] = mapped_column(String(2048))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    logo_media_id: Mapped[int | None] = mapped_column(ForeignKey("media.id"))
    verification_status: Mapped[str] = mapped_column(
        String(16), server_default=text("'unverified'"), default=VerificationStatus.unverified
    )
    # NULL — пока не верифицирована.
    verification_method: Mapped[str | None] = mapped_column(String(16))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class OrgMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "org_members"
    __table_args__ = (enum_check("role", OrgRole), UniqueConstraint("org_id", "user_id"))

    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class OrgInvite(IdMixin, TimestampMixin, Base):
    __tablename__ = "org_invites"
    __table_args__ = (enum_check("role", OrgRole),)

    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    # В БД только хеш одноразового токена (§3.1).
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    grants_verification: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


class VerificationRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "verification_requests"
    __table_args__ = (
        enum_check("method", VerificationMethod),
        enum_check("status", VerificationStatus),
    )

    org_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    method: Mapped[str] = mapped_column(String(16))
    inn: Mapped[str | None] = mapped_column(String(12))
    site_url: Mapped[str | None] = mapped_column(String(2048))
    code: Mapped[str | None] = mapped_column(String(32))
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    registry_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    site_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Последний запуск проверок: повтор не чаще раза в 10 минут.
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
