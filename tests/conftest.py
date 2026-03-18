import asyncio
import hashlib
import secrets
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.config import Settings
from app.main import create_app
from app.models.tables import ApiKey, Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:17-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:7-alpine") as r:
        yield f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"


@pytest.fixture
async def db_engine(postgres_url):
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def master_key():
    return "test-master-key-for-tests"


@pytest.fixture
async def test_api_key(db_session: AsyncSession) -> tuple[str, ApiKey]:
    raw_key = "tempinbox_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=uuid.uuid4(),
        key_hash=key_hash,
        name="test-key",
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return raw_key, api_key


@pytest.fixture
async def restricted_api_key(db_session: AsyncSession) -> tuple[str, ApiKey]:
    raw_key = "tempinbox_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=uuid.uuid4(),
        key_hash=key_hash,
        name="restricted-key",
        is_active=True,
        domains=["restricted.dev"],
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return raw_key, api_key


@pytest.fixture
async def inactive_api_key(db_session: AsyncSession) -> tuple[str, ApiKey]:
    raw_key = "tempinbox_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=uuid.uuid4(),
        key_hash=key_hash,
        name="inactive-key",
        is_active=False,
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return raw_key, api_key


@pytest.fixture
async def expired_api_key(db_session: AsyncSession) -> tuple[str, ApiKey]:
    raw_key = "tempinbox_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = ApiKey(
        id=uuid.uuid4(),
        key_hash=key_hash,
        name="expired-key",
        is_active=True,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return raw_key, api_key


@pytest.fixture
async def redis(redis_url) -> AsyncGenerator[Redis]:
    r = Redis.from_url(redis_url)
    await r.flushdb()
    yield r
    await r.aclose()


@pytest.fixture
async def app(db_engine, redis_url, master_key):
    import os

    os.environ["TEMPINBOX_MASTER_KEY"] = master_key
    os.environ["TEMPINBOX_REDIS_URL"] = redis_url

    application = create_app()

    from app.database import create_session_factory

    settings = Settings()
    session_factory = create_session_factory(db_engine)
    app_redis = Redis.from_url(redis_url)

    application.state.settings = settings
    application.state.engine = db_engine
    application.state.session_factory = session_factory
    application.state.redis = app_redis

    yield application

    await app_redis.aclose()


@pytest.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
