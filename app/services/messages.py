"""Service layer for querying and retrieving email messages."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Message
from app.schemas.messages import InboxStats, MessageDetail, MessageSummary


def _escape_like(value: str) -> str:
    """Escape special characters for ILIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_summary(msg: Message) -> MessageSummary:
    preview = None
    if msg.body_text:
        preview = msg.body_text[:200]
    return MessageSummary(
        id=msg.id,
        sender=msg.sender,
        subject=msg.subject,
        received_at=msg.received_at,
        size_bytes=msg.size_bytes,
        has_html=msg.body_html is not None,
        preview=preview,
    )


async def list_messages(
    db: AsyncSession,
    email_addr: str,
    *,
    limit: int = 50,
    offset: int = 0,
    sort: str = "desc",
    sender: str | None = None,
    subject_contains: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[MessageSummary], int]:
    """Return paginated messages for an inbox, with optional filtering."""
    base = sa.select(Message).where(Message.recipient == email_addr)

    if sender:
        base = base.where(Message.sender.ilike(f"%{_escape_like(sender)}%"))
    if subject_contains:
        base = base.where(Message.subject.ilike(f"%{_escape_like(subject_contains)}%"))
    if date_from:
        base = base.where(Message.received_at >= date_from)
    if date_to:
        base = base.where(Message.received_at <= date_to)

    count_q = sa.select(sa.func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    order = Message.received_at.desc() if sort == "desc" else Message.received_at.asc()
    rows = (await db.execute(base.order_by(order).offset(offset).limit(limit))).scalars().all()

    return [_to_summary(r) for r in rows], total


async def search_messages(
    db: AsyncSession,
    email_addr: str,
    q: str,
    *,
    search_in: str = "all",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MessageSummary], int]:
    """Search messages by subject and/or body text using ILIKE."""
    base = sa.select(Message).where(Message.recipient == email_addr)
    pattern = f"%{_escape_like(q)}%"

    if search_in == "subject":
        base = base.where(Message.subject.ilike(pattern))
    elif search_in == "body":
        base = base.where(
            sa.or_(Message.body_text.ilike(pattern), Message.body_html.ilike(pattern)),
        )
    else:
        base = base.where(
            sa.or_(
                Message.subject.ilike(pattern),
                Message.body_text.ilike(pattern),
                Message.body_html.ilike(pattern),
            ),
        )

    count_q = sa.select(sa.func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows = (
        (await db.execute(base.order_by(Message.received_at.desc()).offset(offset).limit(limit)))
        .scalars()
        .all()
    )
    return [_to_summary(r) for r in rows], total


async def get_inbox_stats(db: AsyncSession, email_addr: str) -> InboxStats:
    """Compute aggregate stats (count, size, date range) for an inbox."""
    q = sa.select(
        sa.func.count().label("total"),
        sa.func.coalesce(sa.func.sum(Message.size_bytes), 0).label("size"),
        sa.func.min(Message.received_at).label("first"),
        sa.func.max(Message.received_at).label("last"),
    ).where(Message.recipient == email_addr)

    row = (await db.execute(q)).one()
    return InboxStats(
        total_messages=row.total,
        total_size_bytes=row.size,
        first_received_at=row.first,
        last_received_at=row.last,
    )


async def get_message(db: AsyncSession, message_id: uuid.UUID) -> MessageDetail | None:
    """Fetch a single message by primary key, or return None."""
    msg = await db.get(Message, message_id)
    if msg is None:
        return None
    return MessageDetail.model_validate(msg)
