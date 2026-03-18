"""SQLAlchemy ORM models for messages, API keys, and blacklist entries."""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Message(Base):
    """An email message received via SMTP."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sender: Mapped[str] = mapped_column(String(320))
    recipient: Mapped[str] = mapped_column(String(320), index=True)
    subject: Mapped[str | None] = mapped_column(String(998))
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    raw_headers: Mapped[dict | None] = mapped_column(JSONB)
    size_bytes: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)

    __table_args__ = (Index("ix_messages_recipient_received_at", "recipient", received_at.desc()),)


class ApiKey(Base):
    """An API key for authenticating public endpoint access."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    domains: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    rate_limit_override: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_requests: Mapped[int] = mapped_column(Integer, default=0)


class BlacklistEntry(Base):
    """A pattern-based rule for blocking senders (hard or soft block)."""

    __tablename__ = "blacklist"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pattern: Mapped[str] = mapped_column(String(320), unique=True)
    block_type: Mapped[str] = mapped_column(String(4), default="hard")  # hard / soft
    reason: Mapped[str | None] = mapped_column(Text)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
