"""Tests for the messages service layer."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.tables import Message
from app.services.messages import (
    _escape_like,
    _to_summary,
    list_messages,
    search_messages,
)


async def _insert(
    db,
    *,
    sender="sender@example.com",
    recipient="user@tempinbox.dev",
    subject="Test",
    body_text="body",
    body_html=None,
    received_at=None,
):
    msg = Message(
        id=uuid.uuid4(),
        sender=sender,
        recipient=recipient,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        raw_headers={},
        size_bytes=100,
        domain="tempinbox.dev",
        received_at=received_at or datetime.now(UTC),
    )
    db.add(msg)
    await db.commit()
    return msg


# --- _escape_like tests ---


def test_escape_like_percent():
    assert _escape_like("50%") == "50\\%"


def test_escape_like_underscore():
    assert _escape_like("a_b") == "a\\_b"


def test_escape_like_backslash():
    assert _escape_like("a\\b") == "a\\\\b"


# --- _to_summary tests ---


def test_to_summary_preview_truncated():
    msg = Message(
        id=uuid.uuid4(),
        sender="a@b.com",
        recipient="x@y.com",
        subject="Sub",
        body_text="A" * 300,
        body_html=None,
        raw_headers={},
        size_bytes=300,
        domain="y.com",
        received_at=datetime.now(UTC),
    )
    summary = _to_summary(msg)
    assert len(summary.preview) == 200
    assert summary.preview == "A" * 200


def test_to_summary_no_body():
    msg = Message(
        id=uuid.uuid4(),
        sender="a@b.com",
        recipient="x@y.com",
        subject="Sub",
        body_text=None,
        body_html=None,
        raw_headers={},
        size_bytes=50,
        domain="y.com",
        received_at=datetime.now(UTC),
    )
    summary = _to_summary(msg)
    assert summary.preview is None


# --- list_messages tests ---


async def test_list_messages_pagination(db_session):
    recipient = f"pag-{uuid.uuid4()}@tempinbox.dev"
    for i in range(5):
        await _insert(
            db_session,
            recipient=recipient,
            received_at=datetime.now(UTC) + timedelta(seconds=i),
        )

    results, total = await list_messages(db_session, recipient, limit=2, offset=0)
    assert total == 5
    assert len(results) == 2


async def test_list_messages_filter_sender(db_session):
    recipient = f"fs-{uuid.uuid4()}@tempinbox.dev"
    await _insert(db_session, recipient=recipient, sender="alice@example.com")
    await _insert(db_session, recipient=recipient, sender="bob@example.com")

    results, total = await list_messages(db_session, recipient, sender="alice")
    assert total == 1
    assert results[0].sender == "alice@example.com"


async def test_list_messages_filter_subject_contains(db_session):
    recipient = f"fsc-{uuid.uuid4()}@tempinbox.dev"
    await _insert(db_session, recipient=recipient, subject="Important notice")
    await _insert(db_session, recipient=recipient, subject="Hello world")

    results, total = await list_messages(db_session, recipient, subject_contains="important")
    assert total == 1
    assert results[0].subject == "Important notice"


async def test_list_messages_filter_date_range(db_session):
    recipient = f"fdr-{uuid.uuid4()}@tempinbox.dev"
    now = datetime.now(UTC)
    await _insert(db_session, recipient=recipient, received_at=now - timedelta(days=5))
    await _insert(db_session, recipient=recipient, received_at=now - timedelta(days=1))
    await _insert(db_session, recipient=recipient, received_at=now)

    results, total = await list_messages(
        db_session,
        recipient,
        date_from=now - timedelta(days=2),
        date_to=now + timedelta(seconds=1),
    )
    assert total == 2


async def test_list_messages_sort_asc(db_session):
    recipient = f"sa-{uuid.uuid4()}@tempinbox.dev"
    t1 = datetime.now(UTC) - timedelta(hours=2)
    t2 = datetime.now(UTC) - timedelta(hours=1)
    t3 = datetime.now(UTC)
    await _insert(db_session, recipient=recipient, received_at=t2)
    await _insert(db_session, recipient=recipient, received_at=t1)
    await _insert(db_session, recipient=recipient, received_at=t3)

    results, total = await list_messages(db_session, recipient, sort="asc")
    assert total == 3
    assert results[0].received_at <= results[1].received_at <= results[2].received_at


# --- search_messages tests ---


async def test_search_messages_subject_only(db_session):
    recipient = f"sso-{uuid.uuid4()}@tempinbox.dev"
    await _insert(
        db_session,
        recipient=recipient,
        subject="UniqueSubjectToken",
        body_text="nothing here",
    )
    await _insert(
        db_session,
        recipient=recipient,
        subject="Other",
        body_text="UniqueSubjectToken in body",
    )

    results, total = await search_messages(
        db_session, recipient, "UniqueSubjectToken", search_in="subject"
    )
    assert total == 1
    assert results[0].subject == "UniqueSubjectToken"


async def test_search_messages_body_only(db_session):
    recipient = f"sbo-{uuid.uuid4()}@tempinbox.dev"
    await _insert(
        db_session,
        recipient=recipient,
        subject="UniqueBodyMarker",
        body_text="nothing here",
    )
    await _insert(
        db_session,
        recipient=recipient,
        subject="Other",
        body_text="UniqueBodyMarker in body",
    )

    results, total = await search_messages(
        db_session, recipient, "UniqueBodyMarker", search_in="body"
    )
    assert total == 1
    assert results[0].subject == "Other"


async def test_search_messages_no_results(db_session):
    recipient = f"snr-{uuid.uuid4()}@tempinbox.dev"
    await _insert(db_session, recipient=recipient, subject="Hello", body_text="world")

    results, total = await search_messages(db_session, recipient, "nonexistent_xyz_12345")
    assert total == 0
    assert results == []
