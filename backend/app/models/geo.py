from geoalchemy2 import Geography, WKBElement
from sqlalchemy import Computed, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, enum_check
from app.models.enums import LocalityKind


class Locality(IdMixin, TimestampMixin, Base):
    __tablename__ = "localities"
    __table_args__ = (
        enum_check("kind", LocalityKind),
        Index("ix_localities_point", "point", postgresql_using="gist"),
        Index(
            "ix_localities_name_norm_trgm",
            "name_norm",
            postgresql_using="gin",
            postgresql_ops={"name_norm": "gin_trgm_ops"},
        ),
        Index(
            "ix_localities_name_norm_prefix",
            "name_norm",
            postgresql_ops={"name_norm": "varchar_pattern_ops"},
        ),
    )

    fias_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Ключ строки справочника (osm-n<id>); у пунктов, созданных вручную, — пусто.
    key: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    # Для поиска: lower, ё→е, дефисы → пробел (зеркало — localities.normalize).
    name_norm: Mapped[str] = mapped_column(
        String(255), Computed("translate(lower(name), 'ё-–', 'е  ')", persisted=True)
    )
    kind: Mapped[str] = mapped_column(String(16))
    region: Mapped[str | None] = mapped_column(String(255))
    region_code: Mapped[str | None] = mapped_column(String(8), index=True)
    municipality: Mapped[str | None] = mapped_column(String(255))
    point: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    timezone: Mapped[str] = mapped_column(String(64))
    population: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))


class Venue(IdMixin, TimestampMixin, Base):
    __tablename__ = "venues"
    __table_args__ = (Index("ix_venues_point", "point", postgresql_using="gist"),)

    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    locality_id: Mapped[int] = mapped_column(ForeignKey("localities.id"), index=True)
    point: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False)
    )
    fias_id: Mapped[str | None] = mapped_column(String(64))
    org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
