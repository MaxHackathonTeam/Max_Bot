"""Вход с сайта без MAX и отказ от внешних источников.

- users.channel: откуда пришёл пользователь (max — бот/мини-приложение, web — сайт, гость);
- удалены журналы LLM-вызовов и импортов, проверка страницы через LLM
  и внешний id организации в стороннем каталоге.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27 10:00:00
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EXTERNAL_ORG_ID = "proculture_org_id"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("channel", sa.String(length=8), server_default=sa.text("'max'"), nullable=False),
    )
    op.create_check_constraint(op.f("ck_users_channel"), "users", "channel IN ('max', 'web')")
    op.drop_index(op.f(f"ix_organizations_{_EXTERNAL_ORG_ID}"), table_name="organizations")
    op.drop_column("organizations", _EXTERNAL_ORG_ID)
    op.drop_column("verification_requests", "llm_check")
    op.drop_index(op.f("ix_llm_calls_purpose"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index(op.f("ix_import_runs_source"), table_name="import_runs")
    op.drop_table("import_runs")


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    ]


def downgrade() -> None:
    op.create_table(
        "import_runs",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index(op.f("ix_import_runs_source"), "import_runs", ["source"])
    op.create_table(
        "llm_calls",
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index(op.f("ix_llm_calls_purpose"), "llm_calls", ["purpose"])
    op.add_column(
        "verification_requests",
        sa.Column("llm_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("organizations", sa.Column(_EXTERNAL_ORG_ID, sa.BigInteger(), nullable=True))
    op.create_index(
        op.f(f"ix_organizations_{_EXTERNAL_ORG_ID}"), "organizations", [_EXTERNAL_ORG_ID]
    )
    op.drop_constraint(op.f("ck_users_channel"), "users", type_="check")
    op.drop_column("users", "channel")
