"""Справочник НП всей России: ключ источника и нормализованное имя для поиска.

key — стабильный ключ строки импорта (osm-n<id>), по нему идёт upsert в `make seed`.
name_norm — lower(name), ё→е, дефисы → пробел; по нему trigram- и префиксный поиск.
Прежний trigram-индекс по name заменяется индексом по name_norm.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_NORM_SQL = "translate(lower(name), 'ё-–', 'е  ')"


def upgrade() -> None:
    op.add_column("localities", sa.Column("key", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_localities_key", "localities", ["key"])
    op.add_column(
        "localities",
        sa.Column(
            "name_norm",
            sa.String(length=255),
            sa.Computed(NAME_NORM_SQL, persisted=True),
            nullable=False,
        ),
    )
    op.drop_index("ix_localities_name_trgm", table_name="localities")
    op.create_index(
        "ix_localities_name_norm_trgm",
        "localities",
        ["name_norm"],
        postgresql_using="gin",
        postgresql_ops={"name_norm": "gin_trgm_ops"},
    )
    # LIKE 'q%' при локали не C использует индекс только с text_pattern_ops.
    op.create_index(
        "ix_localities_name_norm_prefix",
        "localities",
        ["name_norm"],
        postgresql_ops={"name_norm": "varchar_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_localities_name_norm_prefix", table_name="localities")
    op.drop_index("ix_localities_name_norm_trgm", table_name="localities")
    op.create_index(
        "ix_localities_name_trgm",
        "localities",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_column("localities", "name_norm")
    op.drop_constraint("uq_localities_key", "localities", type_="unique")
    op.drop_column("localities", "key")
