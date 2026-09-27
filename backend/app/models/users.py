from datetime import datetime

from geoalchemy2 import Geography, WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, enum_check
from app.models.enums import ConsentDoc, UserChannel


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("radius_km IN (5, 15, 30, 50)", name="radius_km"),
        CheckConstraint(
            "birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100", name="birth_year"
        ),
        enum_check("channel", UserChannel),
    )

    # NULL у гостя сайта и после удаления данных (FR-ONB-5).
    max_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    channel: Mapped[str] = mapped_column(
        String(8), server_default=text("'max'"), default=UserChannel.max
    )
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(16))
    dialog_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    locality_id: Mapped[int | None] = mapped_column(ForeignKey("localities.id"))
    home_point: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    radius_km: Mapped[int] = mapped_column(SmallInteger, server_default=text("30"), default=30)
    interests: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list
    )
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)
    notify_digest: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    notify_reminders: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True
    )
    bot_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Consent(IdMixin, TimestampMixin, Base):
    __tablename__ = "consents"
    __table_args__ = (
        enum_check("doc", ConsentDoc),
        UniqueConstraint("user_id", "doc", "version"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    doc: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
