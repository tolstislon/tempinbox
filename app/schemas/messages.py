"""Pydantic schemas for message-related API responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class MessageSummary(BaseModel):
    """Compact message representation for inbox listings."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    sender: str
    subject: str | None
    received_at: datetime
    size_bytes: int
    has_html: bool
    preview: str | None


class MessageDetail(BaseModel):
    """Full message with body and headers."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    sender: str
    recipient: str
    subject: str | None
    body_text: str | None
    body_html: str | None
    raw_headers: dict[str, list[str]] | None
    received_at: datetime
    size_bytes: int


class InboxResponse(BaseModel):
    """Paginated list of messages with total count."""

    messages: list[MessageSummary]
    total: int


class InboxStats(BaseModel):
    """Aggregate statistics for an inbox."""

    total_messages: int
    total_size_bytes: int
    first_received_at: datetime | None
    last_received_at: datetime | None
