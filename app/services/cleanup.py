"""Background task for deleting expired messages in batches."""

from datetime import timedelta

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.tables import Message

logger = structlog.get_logger()

BATCH_SIZE = 1000


async def cleanup_old_messages(
    session_factory: async_sessionmaker[AsyncSession],
    ttl_hours: int,
) -> int:
    """Delete messages older than ttl_hours in batches of BATCH_SIZE."""
    cutoff = sa.func.now() - timedelta(hours=ttl_hours)
    total_deleted = 0

    while True:
        async with session_factory() as db:
            subq = (
                sa.select(Message.id)
                .where(Message.received_at < cutoff)
                .limit(BATCH_SIZE)
                .subquery()
            )
            result = await db.execute(sa.delete(Message).where(Message.id.in_(sa.select(subq))))
            deleted = result.rowcount
            await db.commit()

        total_deleted += deleted
        if deleted < BATCH_SIZE:
            break

    if total_deleted > 0:
        await logger.ainfo("Cleanup completed", deleted=total_deleted)

    return total_deleted
