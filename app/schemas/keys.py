"""Pydantic schemas for API key and blacklist operations."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    """Request body for creating a new API key."""

    name: str | None = Field(None, max_length=255)
    comment: str | None = Field(None, max_length=2000)
    domains: list[str] | None = None
    rate_limit_override: int | None = None
    expires_at: datetime | None = None


class ApiKeyCreated(BaseModel):
    """Response returned after key creation, including the raw key (shown once)."""

    id: uuid.UUID
    key: str
    name: str | None
    created_at: datetime


class ApiKeyInfo(BaseModel):
    """Read-only representation of an API key (no secret material)."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str | None
    comment: str | None
    is_active: bool
    domains: list[str] | None
    rate_limit_override: int | None
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None
    total_requests: int


class ApiKeyUpdate(BaseModel):
    """Fields that can be patched on an existing API key."""

    name: str | None = Field(None, max_length=255)
    comment: str | None = Field(None, max_length=2000)
    domains: list[str] | None = None
    rate_limit_override: int | None = None
    is_active: bool | None = None


class BlacklistCreate(BaseModel):
    """Request body for adding a blacklist entry."""

    pattern: str = Field(min_length=1, max_length=320)
    block_type: Literal["hard", "soft"] = "hard"
    reason: str | None = None


class BlacklistUpdate(BaseModel):
    """Fields that can be patched on an existing blacklist entry."""

    pattern: str | None = None
    block_type: Literal["hard", "soft"] | None = None
    reason: str | None = None
    is_active: bool | None = None


class BlacklistInfo(BaseModel):
    """Read-only representation of a blacklist entry."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    pattern: str
    block_type: str
    reason: str | None
    blocked_count: int
    is_active: bool
    created_at: datetime


class BlacklistImport(BaseModel):
    """Wrapper for bulk-importing multiple blacklist patterns."""

    patterns: list[BlacklistCreate] = Field(max_length=1000)
