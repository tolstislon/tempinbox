"""Async SQLAlchemy engine and session helpers."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(database_url: str, pool_size: int = 20):  # noqa: ANN201
    """Create an async SQLAlchemy engine with connection pooling."""
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        pool_pre_ping=True,
    )


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:  # noqa: ANN001
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Yield an async session and close it when done."""
    async with factory() as session:
        yield session
