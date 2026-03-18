"""Initial tables: messages, api_keys, blacklist.

Revision ID: 001
Revises:
Create Date: 2026-03-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(998), nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("raw_headers", postgresql.JSONB, nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("domain", sa.String(255), nullable=False),
    )
    op.create_index("ix_messages_recipient", "messages", ["recipient"])
    op.create_index("ix_messages_received_at", "messages", ["received_at"])
    op.create_index("ix_messages_domain", "messages", ["domain"])
    op.create_index(
        "ix_messages_recipient_received_at",
        "messages",
        ["recipient", sa.text("received_at DESC")],
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("domains", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("rate_limit_override", sa.Integer, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_requests", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    op.create_table(
        "blacklist",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pattern", sa.String(320), nullable=False, unique=True),
        sa.Column("block_type", sa.String(4), nullable=False, server_default=sa.text("'hard'")),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("blocked_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("blacklist")
    op.drop_table("api_keys")
    op.drop_table("messages")
