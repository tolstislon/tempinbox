"""Tests for the rate-limit middleware."""

import hashlib
import os
from collections.abc import AsyncGenerator

import httpx
import pytest
from redis.asyncio import Redis

from app.config import Settings
from app.database import create_session_factory
from app.main import create_app


@pytest.fixture
async def low_rate_limit_app(db_engine, redis_url, master_key):
    os.environ["TEMPINBOX_MASTER_KEY"] = master_key
    os.environ["TEMPINBOX_REDIS_URL"] = redis_url
    os.environ["TEMPINBOX_RATE_LIMIT_PER_MINUTE"] = "3"

    application = create_app()

    settings = Settings()
    session_factory = create_session_factory(db_engine)
    app_redis = Redis.from_url(redis_url)
    await app_redis.flushdb()

    application.state.settings = settings
    application.state.engine = db_engine
    application.state.session_factory = session_factory
    application.state.redis = app_redis

    yield application

    await app_redis.aclose()
    os.environ.pop("TEMPINBOX_RATE_LIMIT_PER_MINUTE", None)


@pytest.fixture
async def rl_client(low_rate_limit_app) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=low_rate_limit_app),
        base_url="http://test",
    ) as c:
        yield c


async def test_health_endpoint_bypasses_rate_limit(rl_client):
    """GET /health should always succeed, even after exceeding the limit."""
    for _ in range(10):
        resp = await rl_client.get("/health")
        assert resp.status_code == 200


async def test_rate_limit_header_present(rl_client):
    """Successful requests must include X-RateLimit-Remaining header."""
    resp = await rl_client.get("/api/v1/inbox/test@example.com")
    # The route may return 403/422, but the middleware header should be there
    assert "X-RateLimit-Remaining" in resp.headers


async def test_rate_limit_429_response(rl_client):
    """Exceeding the limit must return 429 with a Retry-After header."""
    for _ in range(3):
        await rl_client.get("/api/v1/inbox/test@example.com")

    resp = await rl_client.get("/api/v1/inbox/test@example.com")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


async def test_rate_limit_per_api_key(rl_client):
    """Different API keys should have independent rate-limit counters."""
    key_a = "tempinbox_aaaa"
    key_b = "tempinbox_bbbb"

    # Exhaust limit for key_a
    for _ in range(3):
        await rl_client.get(
            "/api/v1/inbox/test@example.com",
            headers={"x-api-key": key_a},
        )

    # key_a should be blocked
    resp_a = await rl_client.get(
        "/api/v1/inbox/test@example.com",
        headers={"x-api-key": key_a},
    )
    assert resp_a.status_code == 429

    # key_b should still work
    resp_b = await rl_client.get(
        "/api/v1/inbox/test@example.com",
        headers={"x-api-key": key_b},
    )
    assert resp_b.status_code != 429


async def test_rate_limit_by_ip_without_key(rl_client):
    """Without an API key, rate limiting should use client IP."""
    for _ in range(3):
        await rl_client.get("/api/v1/inbox/test@example.com")

    resp = await rl_client.get("/api/v1/inbox/test@example.com")
    assert resp.status_code == 429

    # A request with an API key should still succeed (different identifier)
    resp_with_key = await rl_client.get(
        "/api/v1/inbox/test@example.com",
        headers={"x-api-key": "tempinbox_some_key"},
    )
    assert resp_with_key.status_code != 429


async def test_rate_limit_override_from_redis(low_rate_limit_app, rl_client):
    """A per-key limit stored in Redis should override the default."""
    api_key = "tempinbox_override_test"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Set a higher per-key limit (10) in Redis
    app_redis = low_rate_limit_app.state.redis
    await app_redis.set(f"api_key_limit:{key_hash}", "10")

    # Should be able to make more than 3 requests (default limit)
    for i in range(6):
        resp = await rl_client.get(
            "/api/v1/inbox/test@example.com",
            headers={"x-api-key": api_key},
        )
        assert resp.status_code != 429, f"Request {i + 1} was rate-limited unexpectedly"


async def test_docs_endpoint_bypasses_rate_limit(rl_client):
    """GET /docs should always pass, regardless of rate limit."""
    for _ in range(10):
        resp = await rl_client.get("/docs")
        # /docs returns 200 (Swagger UI) — middleware never blocks it
        assert resp.status_code != 429


async def test_429_body_contains_detail(rl_client):
    """The 429 response body must contain the expected error detail."""
    for _ in range(3):
        await rl_client.get("/api/v1/inbox/test@example.com")

    resp = await rl_client.get("/api/v1/inbox/test@example.com")
    assert resp.status_code == 429
    body = resp.json()
    assert body == {"detail": "Rate limit exceeded"}
