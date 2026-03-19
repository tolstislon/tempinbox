"""FastAPI application factory with SMTP server and cleanup task lifecycle."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.admin import router as admin_router
from app.api.public import health_router
from app.api.public import router as public_router
from app.config import Settings
from app.database import create_engine, create_session_factory
from app.logging import setup_logging
from app.middleware.rate_limit import RateLimitMiddleware
from app.services.cleanup import cleanup_old_messages
from app.smtp.server import create_smtp_server

logger = structlog.get_logger()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


async def _cleanup_loop(app: FastAPI) -> None:
    """Periodically delete expired messages in the background."""
    settings: Settings = app.state.settings
    while True:
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
        try:
            await cleanup_old_messages(app.state.session_factory, settings.message_ttl_hours)
        except Exception:
            await logger.aexception("Cleanup task failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manage startup/shutdown of DB, Redis, SMTP, and cleanup task."""
    settings = Settings()
    setup_logging(json_format=True)

    if not settings.api_key_hmac_secret:
        await logger.awarning(
            "TEMPINBOX_API_KEY_HMAC_SECRET is not set — API keys use plain SHA-256 hashing"
        )

    engine = create_engine(settings.database_url, pool_size=settings.db_pool_size)
    session_factory = create_session_factory(engine)
    redis = Redis.from_url(settings.redis_url)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis

    # Start SMTP
    smtp_server = await create_smtp_server(session_factory, settings, redis=redis)
    await logger.ainfo("SMTP server started", host=settings.smtp_host, port=settings.smtp_port)

    # Start cleanup task
    cleanup_task = asyncio.create_task(_cleanup_loop(app))

    yield

    cleanup_task.cancel()
    await smtp_server.stop()
    await redis.aclose()
    await engine.dispose()
    await logger.ainfo("Shutdown complete")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = Settings()
    app = FastAPI(
        title="TempInbox",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.include_router(public_router)
    app.include_router(health_router)
    app.include_router(admin_router)
    return app
