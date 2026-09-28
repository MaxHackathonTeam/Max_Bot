"""Составной индекс сеансов (event_id, starts_at) для ленты (§15).

Заменяет ix_event_sessions_event_id: префикс event_id покрывает те же запросы.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28 10:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_event_sessions_event_id_starts_at", "event_sessions", ["event_id", "starts_at"]
    )
    op.drop_index("ix_event_sessions_event_id", table_name="event_sessions")


def downgrade() -> None:
    op.create_index("ix_event_sessions_event_id", "event_sessions", ["event_id"])
    op.drop_index("ix_event_sessions_event_id_starts_at", table_name="event_sessions")
