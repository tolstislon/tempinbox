"""Service layer for sender blacklist management and matching."""

import fnmatch
import json
import uuid

import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import BlacklistEntry
from app.schemas.keys import BlacklistCreate, BlacklistInfo, BlacklistUpdate

_CACHE_KEY = "blacklist:active_entries"
_CACHE_TTL = 60


async def _invalidate_cache(redis: Redis | None) -> None:
    """Remove cached blacklist entries from Redis."""
    if redis is not None:
        await redis.delete(_CACHE_KEY)


async def _get_cached_blacklist(
    redis: Redis | None,
    db: AsyncSession,
) -> list[dict]:
    """Load active blacklist entries, using Redis cache when available."""
    if redis is not None:
        cached = await redis.get(_CACHE_KEY)
        if cached is not None:
            return json.loads(cached)

    result = await db.execute(
        sa.select(
            BlacklistEntry.id,
            BlacklistEntry.pattern,
            BlacklistEntry.block_type,
        ).where(BlacklistEntry.is_active.is_(True)),
    )
    entries = [
        {"id": str(row.id), "pattern": row.pattern, "block_type": row.block_type}
        for row in result.all()
    ]

    if redis is not None:
        await redis.set(_CACHE_KEY, json.dumps(entries), ex=_CACHE_TTL)

    return entries


async def add_entry(
    db: AsyncSession,
    data: BlacklistCreate,
    redis: Redis | None = None,
) -> BlacklistInfo:
    """Create a new blacklist entry."""
    entry = BlacklistEntry(
        pattern=data.pattern,
        block_type=data.block_type,
        reason=data.reason,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    await _invalidate_cache(redis)
    return BlacklistInfo.model_validate(entry)


async def list_entries(db: AsyncSession) -> list[BlacklistInfo]:
    """Return all blacklist entries ordered by creation date (newest first)."""
    result = await db.execute(
        sa.select(BlacklistEntry).order_by(BlacklistEntry.created_at.desc()),
    )
    return [BlacklistInfo.model_validate(e) for e in result.scalars().all()]


async def delete_entry(
    db: AsyncSession,
    entry_id: uuid.UUID,
    redis: Redis | None = None,
) -> bool:
    """Delete a blacklist entry by ID. Returns False if not found."""
    entry = await db.get(BlacklistEntry, entry_id)
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    await _invalidate_cache(redis)
    return True


async def update_entry(
    db: AsyncSession,
    entry_id: uuid.UUID,
    data: BlacklistUpdate,
    redis: Redis | None = None,
) -> BlacklistInfo | None:
    """Apply partial updates to a blacklist entry."""
    entry = await db.get(BlacklistEntry, entry_id)
    if entry is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(entry, field, value)

    await db.commit()
    await db.refresh(entry)
    await _invalidate_cache(redis)
    return BlacklistInfo.model_validate(entry)


async def import_entries(
    db: AsyncSession,
    entries: list[BlacklistCreate],
    redis: Redis | None = None,
) -> list[BlacklistInfo]:
    """Bulk-import blacklist patterns, skipping any that already exist."""
    results = []
    for data in entries:
        existing = await db.execute(
            sa.select(BlacklistEntry).where(BlacklistEntry.pattern == data.pattern),
        )
        if existing.scalar_one_or_none() is not None:
            continue
        results.append(await add_entry(db, data, redis))
    return results


async def check_blacklist(
    db: AsyncSession,
    sender: str,
    redis: Redis | None = None,
) -> str | None:
    """Returns block_type ('hard'/'soft') if sender is blocked, else None."""
    entries = await _get_cached_blacklist(redis, db)

    sender_lower = sender.lower()
    sender_domain = sender_lower.rsplit("@", 1)[-1] if "@" in sender_lower else sender_lower

    for entry in entries:
        pattern = entry["pattern"].lower()
        if (
            fnmatch.fnmatch(sender_lower, pattern)
            or fnmatch.fnmatch(sender_domain, pattern)
            or sender_lower == pattern
            or sender_domain == pattern
        ):
            # Increment blocked_count asynchronously
            await db.execute(
                sa.update(BlacklistEntry)
                .where(BlacklistEntry.id == uuid.UUID(entry["id"]))
                .values(blocked_count=BlacklistEntry.blocked_count + 1),
            )
            await db.commit()
            return entry["block_type"]

    return None
