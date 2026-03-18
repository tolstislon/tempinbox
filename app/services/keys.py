"""Service layer for API key creation, validation, and management."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import ApiKey
from app.schemas.keys import ApiKeyCreate, ApiKeyCreated, ApiKeyInfo, ApiKeyUpdate


def hash_key(raw_key: str, *, secret: str = "") -> str:
    """Return the hex digest of a raw API key.

    Uses HMAC-SHA256 when a secret is provided, plain SHA-256 otherwise.
    """
    if secret:
        return hmac.new(secret.encode(), raw_key.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def create_api_key(
    db: AsyncSession,
    data: ApiKeyCreate,
    *,
    prefix: str = "tempinbox_",
    hmac_secret: str = "",
    key_length: int = 48,
) -> ApiKeyCreated:
    """Generate a new API key, store its hash, and return the raw key once."""
    raw_key = prefix + secrets.token_urlsafe(key_length)
    key_hash = hash_key(raw_key, secret=hmac_secret)

    api_key = ApiKey(
        key_hash=key_hash,
        name=data.name,
        comment=data.comment,
        domains=data.domains,
        rate_limit_override=data.rate_limit_override,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiKeyCreated(
        id=api_key.id,
        key=raw_key,
        name=api_key.name,
        created_at=api_key.created_at,
    )


async def list_api_keys(db: AsyncSession) -> list[ApiKeyInfo]:
    """Return all API keys ordered by creation date (newest first)."""
    result = await db.execute(sa.select(ApiKey).order_by(ApiKey.created_at.desc()))
    return [ApiKeyInfo.model_validate(k) for k in result.scalars().all()]


async def get_api_key_by_id(db: AsyncSession, key_id: uuid.UUID) -> ApiKeyInfo | None:
    """Look up an API key by its UUID."""
    api_key = await db.get(ApiKey, key_id)
    if api_key is None:
        return None
    return ApiKeyInfo.model_validate(api_key)


async def update_api_key(
    db: AsyncSession,
    key_id: uuid.UUID,
    data: ApiKeyUpdate,
) -> ApiKeyInfo | None:
    """Apply partial updates to an API key."""
    api_key = await db.get(ApiKey, key_id)
    if api_key is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(api_key, field, value)

    await db.commit()
    await db.refresh(api_key)
    return ApiKeyInfo.model_validate(api_key)


async def deactivate_api_key(db: AsyncSession, key_id: uuid.UUID) -> bool:
    """Set is_active=False on an API key. Returns False if not found."""
    api_key = await db.get(ApiKey, key_id)
    if api_key is None:
        return False
    api_key.is_active = False
    await db.commit()
    return True


async def validate_api_key(
    db: AsyncSession,
    raw_key: str,
    *,
    hmac_secret: str = "",
    redis: Redis | None = None,
) -> ApiKey | None:
    """Hash the raw key, look it up, and verify it is active and not expired."""
    key_hash_val = hash_key(raw_key, secret=hmac_secret)
    result = await db.execute(sa.select(ApiKey).where(ApiKey.key_hash == key_hash_val))
    api_key = result.scalar_one_or_none()

    if api_key is None or not api_key.is_active:
        return None

    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        return None

    # Atomic counter update without loading the object again
    await db.execute(
        sa.update(ApiKey)
        .where(ApiKey.id == api_key.id)
        .values(last_used_at=datetime.now(UTC), total_requests=ApiKey.total_requests + 1),
    )
    await db.commit()

    # Cache rate_limit_override in Redis for middleware lookup
    if redis is not None and api_key.rate_limit_override is not None:
        await redis.set(
            f"api_key_limit:{key_hash_val}",
            str(api_key.rate_limit_override),
            ex=60,
        )

    return api_key
