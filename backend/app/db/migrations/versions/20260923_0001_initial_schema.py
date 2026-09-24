"""Начальная схема §10: расширения, таблицы, индексы, роль приложения, неизменяемый audit_log.

Revision ID: 0001
Revises:
Create Date: 2026-09-23 18:15:50.174808
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_ROLE = "afisha_app"

# Таблицы в порядке создания — для downgrade в обратном порядке.
TABLES = [
    "audit_log",
    "import_runs",
    "llm_calls",
    "localities",
    "users",
    "analytics_events",
    "consents",
    "media",
    "moderation_decisions",
    "notifications",
    "organizations",
    "event_drafts",
    "org_invites",
    "org_members",
    "subscriptions",
    "venues",
    "verification_requests",
    "events",
    "event_sessions",
    "event_sources",
    "reports",
    "saved_sessions",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "audit_log",
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=True),
        sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'admin', 'system', 'llm')", name=op.f("ck_audit_log_actor_type")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_table(
        "import_runs",
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_runs")),
    )
    op.create_index(op.f("ix_import_runs_source"), "import_runs", ["source"], unique=False)
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
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_purpose"), "llm_calls", ["purpose"], unique=False)
    op.create_table(
        "localities",
        sa.Column("fias_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("region_code", sa.String(length=8), nullable=True),
        sa.Column("municipality", sa.String(length=255), nullable=True),
        sa.Column(
            "point",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("population", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('city', 'town', 'pgt', 'village', 'settlement', 'other')",
            name=op.f("ck_localities_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_localities")),
        sa.UniqueConstraint("fias_id", name=op.f("uq_localities_fias_id")),
    )
    op.create_index(
        "ix_localities_name_trgm",
        "localities",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_localities_point", "localities", ["point"], unique=False, postgresql_using="gist"
    )
    op.create_index(op.f("ix_localities_region_code"), "localities", ["region_code"], unique=False)
    op.create_table(
        "users",
        sa.Column("max_user_id", sa.BigInteger(), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=16), nullable=True),
        sa.Column("dialog_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("locality_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "home_point",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
            ),
            nullable=True,
        ),
        sa.Column("radius_km", sa.SmallInteger(), server_default=sa.text("30"), nullable=False),
        sa.Column(
            "interests", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("birth_year", sa.SmallInteger(), nullable=True),
        sa.Column("notify_digest", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("notify_reminders", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("bot_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100",
            name=op.f("ck_users_birth_year"),
        ),
        sa.CheckConstraint("radius_km IN (5, 15, 30, 50)", name=op.f("ck_users_radius_km")),
        sa.ForeignKeyConstraint(
            ["locality_id"], ["localities.id"], name=op.f("fk_users_locality_id_localities")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("max_user_id", name=op.f("uq_users_max_user_id")),
    )
    op.create_table(
        "analytics_events",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "props",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_analytics_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analytics_events")),
    )
    op.create_index(
        "ix_analytics_events_name_created_at",
        "analytics_events",
        ["name", "created_at"],
        unique=False,
    )
    op.create_table(
        "consents",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("doc", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("doc IN ('terms', 'privacy', 'org_pd')", name=op.f("ck_consents_doc")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_consents_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
        sa.UniqueConstraint(
            "user_id", "doc", "version", name=op.f("uq_consents_user_id_doc_version")
        ),
    )
    op.create_index(op.f("ix_consents_user_id"), "consents", ["user_id"], unique=False)
    op.create_table(
        "media",
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=op.f("fk_media_owner_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media")),
    )
    op.create_index(op.f("ix_media_owner_user_id"), "media", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_media_sha256"), "media", ["sha256"], unique=False)
    op.create_table(
        "moderation_decisions",
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.REAL(), nullable=True),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('rules', 'llm', 'admin')",
            name=op.f("ck_moderation_decisions_actor_type"),
        ),
        sa.CheckConstraint(
            "verdict IN ('approve', 'reject', 'review', 'hide')",
            name=op.f("ck_moderation_decisions_verdict"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_moderation_decisions_actor_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_moderation_decisions")),
    )
    op.create_index(
        "ix_moderation_decisions_entity",
        "moderation_decisions",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'scheduled'"), nullable=False
        ),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'sent', 'failed', 'skipped')",
            name=op.f("ck_notifications_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedup_key", name=op.f("uq_notifications_dedup_key")),
    )
    op.create_index(
        "ix_notifications_status_scheduled_at",
        "notifications",
        ["status", "scheduled_at"],
        unique=False,
    )
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=True),
        sa.Column("ogrn", sa.String(length=15), nullable=True),
        sa.Column("registry_name", sa.Text(), nullable=True),
        sa.Column("registry_status", sa.String(length=32), nullable=True),
        sa.Column("locality_id", sa.BigInteger(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column("vk_url", sa.String(length=2048), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("logo_media_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default=sa.text("'unverified'"),
            nullable=False,
        ),
        sa.Column("verification_method", sa.String(length=16), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("proculture_org_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('dk', 'museum', 'park', 'library', 'theatre', 'cinema', 'sport', 'nko', 'ip', 'club', 'municipal', 'other')",
            name=op.f("ck_organizations_kind"),
        ),
        sa.CheckConstraint(
            "verification_method IN ('invite', 'registry_auto', 'manual')",
            name=op.f("ck_organizations_verification_method"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified', 'pending', 'verified', 'rejected', 'revoked')",
            name=op.f("ck_organizations_verification_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_organizations_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["locality_id"], ["localities.id"], name=op.f("fk_organizations_locality_id_localities")
        ),
        sa.ForeignKeyConstraint(
            ["logo_media_id"], ["media.id"], name=op.f("fk_organizations_logo_media_id_media")
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_user_id"],
            ["users.id"],
            name=op.f("fk_organizations_verified_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_index(op.f("ix_organizations_inn"), "organizations", ["inn"], unique=False)
    op.create_index(
        op.f("ix_organizations_proculture_org_id"),
        "organizations",
        ["proculture_org_id"],
        unique=False,
    )
    op.create_table(
        "event_drafts",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("org_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "ai_fields", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('bot_text', 'bot_photo', 'form')", name=op.f("ck_event_drafts_origin")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_event_drafts_org_id_organizations")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_event_drafts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_drafts")),
    )
    op.create_index(op.f("ix_event_drafts_user_id"), "event_drafts", ["user_id"], unique=False)
    op.create_table(
        "org_invites",
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "grants_verification", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.BigInteger(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'editor')", name=op.f("ck_org_invites_role")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_org_invites_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_invites_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["used_by"], ["users.id"], name=op.f("fk_org_invites_used_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_org_invites_token_hash")),
    )
    op.create_table(
        "org_members",
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("invited_by", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'editor')", name=op.f("ck_org_members_role")),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.id"], name=op.f("fk_org_members_invited_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_members_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_org_members_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_members")),
        sa.UniqueConstraint("org_id", "user_id", name=op.f("uq_org_members_org_id_user_id")),
    )
    op.create_index(op.f("ix_org_members_user_id"), "org_members", ["user_id"], unique=False)
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("org_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('organization', 'digest')", name=op.f("ck_subscriptions_kind")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_subscriptions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint(
            "user_id",
            "kind",
            "org_id",
            name=op.f("uq_subscriptions_user_id_kind_org_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(op.f("ix_subscriptions_org_id"), "subscriptions", ["org_id"], unique=False)
    op.create_table(
        "venues",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("locality_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "point",
            geoalchemy2.types.Geography(
                geometry_type="POINT",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("fias_id", sa.String(length=64), nullable=True),
        sa.Column("org_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["locality_id"], ["localities.id"], name=op.f("fk_venues_locality_id_localities")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_venues_org_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venues")),
    )
    op.create_index(op.f("ix_venues_locality_id"), "venues", ["locality_id"], unique=False)
    op.create_index(op.f("ix_venues_org_id"), "venues", ["org_id"], unique=False)
    op.create_index("ix_venues_point", "venues", ["point"], unique=False, postgresql_using="gist")
    op.create_table(
        "verification_requests",
        sa.Column("org_id", sa.BigInteger(), nullable=False),
        sa.Column("submitted_by", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("inn", sa.String(length=12), nullable=True),
        sa.Column("site_url", sa.String(length=2048), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=True),
        sa.Column("phone_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("registry_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("site_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "method IN ('invite', 'registry_auto', 'manual')",
            name=op.f("ck_verification_requests_method"),
        ),
        sa.CheckConstraint(
            "status IN ('unverified', 'pending', 'verified', 'rejected', 'revoked')",
            name=op.f("ck_verification_requests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_verification_requests_decided_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_verification_requests_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["users.id"], name=op.f("fk_verification_requests_submitted_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_requests")),
    )
    op.create_index(
        op.f("ix_verification_requests_org_id"), "verification_requests", ["org_id"], unique=False
    )
    op.create_table(
        "events",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("short_description", sa.String(length=512), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("cover_media_id", sa.BigInteger(), nullable=True),
        sa.Column("cover_url", sa.String(length=2048), nullable=True),
        sa.Column("organization_id", sa.BigInteger(), nullable=True),
        sa.Column("author_user_id", sa.BigInteger(), nullable=True),
        sa.Column("trust_tier", sa.String(length=16), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("venue_id", sa.BigInteger(), nullable=True),
        sa.Column("locality_id", sa.BigInteger(), nullable=True),
        sa.Column("is_online", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("online_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "indoor", sa.String(length=16), server_default=sa.text("'unknown'"), nullable=False
        ),
        sa.Column(
            "price_type", sa.String(length=16), server_default=sa.text("'unknown'"), nullable=False
        ),
        sa.Column("price_min", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("price_max", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("pushkin_card", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("age_rating", sa.SmallInteger(), nullable=True),
        sa.Column("youth_score", sa.REAL(), nullable=True),
        sa.Column(
            "registration_required", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("ticket_url", sa.String(length=2048), nullable=True),
        sa.Column("contacts", sa.Text(), nullable=True),
        sa.Column("accessibility", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "locked_fields",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "ai_fields", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("moderation_reason", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "setweight(to_tsvector('russian', coalesce(title, '')), 'A') || setweight(to_tsvector('russian', coalesce(short_description, '')), 'B') || setweight(to_tsvector('russian', coalesce(description, '')), 'C')",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "indoor IN ('indoor', 'outdoor', 'mixed', 'unknown')", name=op.f("ck_events_indoor")
        ),
        sa.CheckConstraint(
            "price_type IN ('free', 'paid', 'donation', 'unknown')",
            name=op.f("ck_events_price_type"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'published', 'rejected', 'cancelled', 'hidden', 'archived')",
            name=op.f("ck_events_status"),
        ),
        sa.CheckConstraint(
            "trust_tier IN ('official', 'community', 'demo')", name=op.f("ck_events_trust_tier")
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], name=op.f("fk_events_author_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["cover_media_id"], ["media.id"], name=op.f("fk_events_cover_media_id_media")
        ),
        sa.ForeignKeyConstraint(
            ["locality_id"], ["localities.id"], name=op.f("fk_events_locality_id_localities")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_events_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"], ["venues.id"], name=op.f("fk_events_venue_id_venues")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
    )
    op.create_index(op.f("ix_events_author_user_id"), "events", ["author_user_id"], unique=False)
    op.create_index(op.f("ix_events_category"), "events", ["category"], unique=False)
    op.create_index(op.f("ix_events_content_hash"), "events", ["content_hash"], unique=False)
    op.create_index(op.f("ix_events_locality_id"), "events", ["locality_id"], unique=False)
    op.create_index(op.f("ix_events_organization_id"), "events", ["organization_id"], unique=False)
    op.create_index(
        "ix_events_search_tsv", "events", ["search_tsv"], unique=False, postgresql_using="gin"
    )
    op.create_index("ix_events_status_trust_tier", "events", ["status", "trust_tier"], unique=False)
    op.create_index("ix_events_tags", "events", ["tags"], unique=False, postgresql_using="gin")
    op.create_index(
        "ix_events_title_trgm",
        "events",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_events_venue_id"), "events", ["venue_id"], unique=False)
    op.create_table(
        "event_sessions",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'scheduled'"), nullable=False
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'cancelled')", name=op.f("ck_event_sessions_status")
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_sessions_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_sessions")),
    )
    op.create_index(
        op.f("ix_event_sessions_event_id"), "event_sessions", ["event_id"], unique=False
    )
    op.create_index(
        op.f("ix_event_sessions_starts_at"), "event_sessions", ["starts_at"], unique=False
    )
    op.create_table(
        "event_sources",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name=op.f("fk_event_sources_event_id_events"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_sources")),
        sa.UniqueConstraint("source", "source_id", name=op.f("uq_event_sources_source_source_id")),
    )
    op.create_index(op.f("ix_event_sources_event_id"), "event_sources", ["event_id"], unique=False)
    op.create_table(
        "reports",
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason IN ('fraud', 'wrong_data', 'offensive', 'not_event', 'other')",
            name=op.f("ck_reports_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"], ["events.id"], name=op.f("fk_reports_event_id_events"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_reports_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint("event_id", "user_id", name=op.f("uq_reports_event_id_user_id")),
    )
    op.create_index(op.f("ix_reports_user_id"), "reports", ["user_id"], unique=False)
    op.create_table(
        "saved_sessions",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["event_sessions.id"],
            name=op.f("fk_saved_sessions_session_id_event_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_sessions")),
        sa.UniqueConstraint(
            "user_id", "session_id", name=op.f("uq_saved_sessions_user_id_session_id")
        ),
    )
    op.create_index(
        op.f("ix_saved_sessions_session_id"), "saved_sessions", ["session_id"], unique=False
    )

    _create_app_role()
    _protect_audit_log()


def _create_app_role() -> None:
    """Роль приложения: только DML, без DDL (§14). Пароль и LOGIN — app.db.roles."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT CONNECT ON DATABASE {op.get_bind().engine.url.database} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )
    # audit_log — только INSERT и SELECT.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE}")


def _protect_audit_log() -> None:
    """Триггер запрещает UPDATE/DELETE/TRUNCATE даже владельцу таблицы."""
    op.execute(
        """
        CREATE FUNCTION audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log: изменение и удаление записей запрещены';
        END
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_log_immutable()"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {APP_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {APP_ROLE}")
    # Роль и расширения не удаляем: роль может владеть объектами в других БД,
    # расширения — общие для кластера.
