"""Поиск организаций: trigram-индекс по названию.

Открытый профиль и каталог организаций (`GET /orgs/search`) ищут по названию нечётко —
через pg_trgm (`%>` и word_similarity), как лента событий.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_organizations_name_trgm",
        "organizations",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_organizations_name_trgm", table_name="organizations")
