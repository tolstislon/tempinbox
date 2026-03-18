"""Public API endpoints for inbox access, message retrieval, and key info."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_api_key, get_db, verify_domain_access
from app.models.tables import ApiKey
from app.schemas.keys import ApiKeyInfo
from app.schemas.messages import InboxResponse, InboxStats, MessageDetail
from app.services import messages as msg_service

router = APIRouter(prefix="/api/v1", tags=["public"])


@router.get("/inbox/{email}")
async def list_inbox(
    email: str = Path(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("desc", pattern="^(asc|desc)$"),
    sender: str | None = None,
    subject_contains: str | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    key: ApiKey = Depends(get_api_key),
) -> InboxResponse:
    """List messages for a given email address with optional filters."""
    verify_domain_access(email, key)
    items, total = await msg_service.list_messages(
        db,
        email,
        limit=limit,
        offset=offset,
        sort=sort,
        sender=sender,
        subject_contains=subject_contains,
        date_from=date_from,
        date_to=date_to,
    )
    return InboxResponse(messages=items, total=total)


@router.get("/inbox/{email}/search")
async def search_inbox(
    email: str = Path(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    q: str = Query(min_length=1),
    search_in: str = Query("all", pattern="^(all|subject|body)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    key: ApiKey = Depends(get_api_key),
) -> InboxResponse:
    """Full-text search across subject and/or body of an inbox."""
    verify_domain_access(email, key)
    items, total = await msg_service.search_messages(
        db,
        email,
        q,
        search_in=search_in,
        limit=limit,
        offset=offset,
    )
    return InboxResponse(messages=items, total=total)


@router.get("/inbox/{email}/stats")
async def inbox_stats(
    email: str = Path(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
    db: AsyncSession = Depends(get_db),
    key: ApiKey = Depends(get_api_key),
) -> InboxStats:
    """Return aggregate statistics for an inbox."""
    verify_domain_access(email, key)
    return await msg_service.get_inbox_stats(db, email)


@router.get("/message/{message_id}")
async def get_message(
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    key: ApiKey = Depends(get_api_key),
) -> MessageDetail:
    """Retrieve a single message by ID with full body and headers."""
    msg = await msg_service.get_message(db, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    verify_domain_access(msg.recipient, key)
    return msg


@router.get("/rate-limit")
async def rate_limit_info(
    request: Request,
    key: ApiKey = Depends(get_api_key),
) -> dict:
    """Return the current rate limit for the authenticated API key."""
    settings = request.app.state.settings
    limit = key.rate_limit_override or settings.rate_limit_per_minute
    return {"limit_per_minute": limit, "key_id": str(key.id)}


@router.get("/key-info")
async def key_info(
    key: ApiKey = Depends(get_api_key),
) -> ApiKeyInfo:
    """Return metadata about the authenticated API key."""
    return ApiKeyInfo.model_validate(key)


health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health(request: Request) -> dict:
    """Check database and Redis connectivity."""
    checks: dict[str, str] = {}

    try:
        async with request.app.state.session_factory() as db:
            from sqlalchemy import text

            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    try:
        redis: Redis = request.app.state.redis
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    status = "healthy" if all(v == "ok" for v in checks.values()) else "unhealthy"
    return {"status": status, "checks": checks}
