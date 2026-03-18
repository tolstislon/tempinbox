"""Admin API endpoints for managing API keys, blacklist, and messages."""

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis, get_settings, require_master_key
from app.config import Settings
from app.models.tables import ApiKey, BlacklistEntry, Message
from app.schemas.keys import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyInfo,
    ApiKeyUpdate,
    BlacklistCreate,
    BlacklistImport,
    BlacklistInfo,
    BlacklistUpdate,
)
from app.services import blacklist as bl_service
from app.services import keys as key_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_master_key)],
)

audit_log = structlog.get_logger("audit")


# --- API Keys ---


@router.post("/keys")
async def create_key(
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApiKeyCreated:
    """Generate a new API key."""
    result = await key_service.create_api_key(
        db,
        data,
        prefix=settings.api_key_prefix,
        hmac_secret=settings.api_key_hmac_secret,
        key_length=settings.api_key_length,
    )
    await audit_log.ainfo("API key created", key_id=str(result.id), name=data.name)
    return result


@router.get("/keys")
async def list_keys(
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyInfo]:
    """List all API keys."""
    return await key_service.list_api_keys(db)


@router.get("/keys/{key_id}")
async def get_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyInfo:
    """Get a single API key by ID."""
    result = await key_service.get_api_key_by_id(db, key_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return result


@router.patch("/keys/{key_id}")
async def update_key(
    key_id: uuid.UUID,
    data: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyInfo:
    """Partially update an API key's fields."""
    result = await key_service.update_api_key(db, key_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Key not found")
    await audit_log.ainfo(
        "API key updated",
        key_id=str(key_id),
        fields=list(data.model_dump(exclude_unset=True)),
    )
    return result


@router.delete("/keys/{key_id}")
async def delete_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete (deactivate) an API key."""
    if not await key_service.deactivate_api_key(db, key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    await audit_log.ainfo("API key deactivated", key_id=str(key_id))
    return {"status": "deactivated"}


# --- Blacklist ---


@router.post("/blacklist")
async def add_blacklist(
    data: BlacklistCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> BlacklistInfo:
    """Add a sender pattern to the blacklist."""
    result = await bl_service.add_entry(db, data, redis=redis)
    await audit_log.ainfo("Blacklist entry created", pattern=data.pattern)
    return result


@router.get("/blacklist")
async def list_blacklist(
    db: AsyncSession = Depends(get_db),
) -> list[BlacklistInfo]:
    """List all blacklist entries."""
    return await bl_service.list_entries(db)


@router.delete("/blacklist/{entry_id}")
async def delete_blacklist(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Remove a blacklist entry."""
    if not await bl_service.delete_entry(db, entry_id, redis=redis):
        raise HTTPException(status_code=404, detail="Entry not found")
    await audit_log.ainfo("Blacklist entry deleted", entry_id=str(entry_id))
    return {"status": "deleted"}


@router.patch("/blacklist/{entry_id}")
async def update_blacklist(
    entry_id: uuid.UUID,
    data: BlacklistUpdate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> BlacklistInfo:
    """Update a blacklist entry's fields."""
    result = await bl_service.update_entry(db, entry_id, data, redis=redis)
    if result is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    await audit_log.ainfo(
        "Blacklist entry updated",
        entry_id=str(entry_id),
        fields=list(data.model_dump(exclude_unset=True)),
    )
    return result


@router.post("/blacklist/import")
async def import_blacklist(
    data: BlacklistImport,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> list[BlacklistInfo]:
    """Bulk-import blacklist patterns, skipping duplicates."""
    result = await bl_service.import_entries(db, data.patterns, redis=redis)
    await audit_log.ainfo("Blacklist import", count=len(result))
    return result


# --- Messages management ---


@router.delete("/messages/old")
async def delete_old_messages(
    days: int = Query(3, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete messages older than the specified number of days."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(sa.delete(Message).where(Message.received_at < cutoff))
    await db.commit()
    await audit_log.ainfo("Old messages deleted", days=days, deleted=result.rowcount)
    return {"deleted": result.rowcount}


@router.delete("/inbox/{email}")
async def clear_inbox(
    email: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete all messages for a specific email address."""
    result = await db.execute(sa.delete(Message).where(Message.recipient == email))
    await db.commit()
    await audit_log.ainfo("Inbox cleared", email=email, deleted=result.rowcount)
    return {"deleted": result.rowcount}


@router.get("/stats")
async def admin_stats(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return system-wide statistics (messages, keys, blacklist, storage)."""
    msg_count = (await db.execute(sa.select(sa.func.count()).select_from(Message))).scalar_one()
    key_count = (await db.execute(sa.select(sa.func.count()).select_from(ApiKey))).scalar_one()
    bl_count = (
        await db.execute(sa.select(sa.func.count()).select_from(BlacklistEntry))
    ).scalar_one()
    total_size = (
        await db.execute(sa.select(sa.func.coalesce(sa.func.sum(Message.size_bytes), 0)))
    ).scalar_one()

    return {
        "total_messages": msg_count,
        "total_api_keys": key_count,
        "total_blacklist_entries": bl_count,
        "total_storage_bytes": total_size,
    }
