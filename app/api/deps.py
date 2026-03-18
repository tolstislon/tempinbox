"""FastAPI dependency injection helpers for auth, DB, and settings."""

import secrets
from collections.abc import AsyncGenerator

import structlog
from fastapi import Depends, Header, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.tables import ApiKey
from app.services.keys import validate_api_key
from app.services.rate_limiter import check_and_record_admin_attempt, reset_admin_auth_counter

logger = structlog.get_logger()


def get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For from trusted proxies."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def get_settings(request: Request) -> Settings:
    """Extract settings from application state."""
    return request.app.state.settings


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    """Yield a database session from the app-level session factory."""
    async with request.app.state.session_factory() as session:
        yield session


async def get_redis(request: Request) -> Redis:
    """Extract Redis client from application state."""
    return request.app.state.redis


def verify_domain_access(email: str, key: ApiKey) -> None:
    """Raise 403 if the API key is restricted to specific domains and email doesn't match."""
    if not key.domains:
        return
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if domain not in [d.lower() for d in key.domains]:
        raise HTTPException(status_code=403, detail="Access denied for this domain")


async def get_api_key(
    request: Request,
    x_api_key: str = Header(),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> ApiKey:
    """Validate the X-API-Key header and return the corresponding ApiKey record."""
    api_key = await validate_api_key(
        db,
        x_api_key,
        hmac_secret=settings.api_key_hmac_secret,
        redis=redis,
    )
    if api_key is None:
        ip = get_client_ip(request)
        await logger.awarning("Invalid API key attempt", ip=ip)
        raise HTTPException(status_code=401, detail="Invalid or expired API key")
    return api_key


async def require_master_key(
    request: Request,
    x_master_key: str = Header(),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> None:
    """Verify the X-Master-Key header matches the configured master key."""
    ip = get_client_ip(request)

    if await check_and_record_admin_attempt(redis, ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts")

    if not secrets.compare_digest(x_master_key, settings.master_key):
        await logger.awarning("Invalid master key attempt", ip=ip)
        raise HTTPException(status_code=401, detail="Invalid master key")

    await reset_admin_auth_counter(redis, ip)
