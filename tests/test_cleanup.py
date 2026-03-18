import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Message
from app.services.cleanup import cleanup_old_messages


async def _insert_message(db: AsyncSession, hours_ago: int) -> uuid.UUID:
    msg_id = uuid.uuid4()
    msg = Message(
        id=msg_id,
        sender="sender@example.com",
        recipient="user@tempinbox.dev",
        subject="Test",
        body_text="body",
        size_bytes=100,
        domain="tempinbox.dev",
        received_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )
    db.add(msg)
    await db.commit()
    return msg_id


async def test_cleanup_old_messages(session_factory):
    async with session_factory() as db:
        old_id = await _insert_message(db, hours_ago=100)
        new_id = await _insert_message(db, hours_ago=1)

    deleted = await cleanup_old_messages(session_factory, ttl_hours=72)

    assert deleted == 1

    async with session_factory() as db:
        old = await db.get(Message, old_id)
        new = await db.get(Message, new_id)
        assert old is None
        assert new is not None


async def test_cleanup_no_old_messages(session_factory):
    deleted = await cleanup_old_messages(session_factory, ttl_hours=72)
    assert deleted == 0
