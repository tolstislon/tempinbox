import pytest
from sqlalchemy import select

from app.config import Settings
from app.models.tables import BlacklistEntry, Message
from app.smtp.server import TempInboxHandler


@pytest.fixture
def settings(master_key):
    import os

    os.environ["TEMPINBOX_MASTER_KEY"] = master_key
    return Settings()


@pytest.fixture
def handler(session_factory, settings):
    return TempInboxHandler(session_factory, settings)


@pytest.fixture
def handler_with_redis(session_factory, settings, redis):
    return TempInboxHandler(session_factory, settings, redis=redis)


class MockEnvelope:
    def __init__(self, mail_from: str, rcpt_tos: list[str], content: bytes):
        self.mail_from = mail_from
        self.rcpt_tos = rcpt_tos
        self.content = content


class MockSession:
    pass


async def test_handle_data_saves_message(handler, session_factory):
    raw_email = (
        b"From: sender@example.com\r\n"
        b"To: user@tempinbox.dev\r\n"
        b"Subject: SMTP Test\r\n"
        b"\r\n"
        b"Hello from SMTP!"
    )

    envelope = MockEnvelope(
        mail_from="sender@example.com",
        rcpt_tos=["user@tempinbox.dev"],
        content=raw_email,
    )

    result = await handler.handle_DATA(None, MockSession(), envelope)
    assert result == "250 Message accepted"

    async with session_factory() as db:
        msgs = (
            (await db.execute(select(Message).where(Message.recipient == "user@tempinbox.dev")))
            .scalars()
            .all()
        )
        assert len(msgs) >= 1
        msg = msgs[-1]
        assert msg.subject == "SMTP Test"
        assert "Hello from SMTP!" in (msg.body_text or "")


async def test_handle_data_rejects_oversized(handler, session_factory):
    handler.settings.max_email_size = 100
    raw_email = b"Subject: big\r\n\r\n" + b"x" * 200

    envelope = MockEnvelope(
        mail_from="sender@example.com",
        rcpt_tos=["user@tempinbox.dev"],
        content=raw_email,
    )

    result = await handler.handle_DATA(None, MockSession(), envelope)
    assert "552" in result


async def test_handle_rcpt_rejects_wrong_domain(handler):
    from aiosmtpd.smtp import Envelope

    envelope = Envelope()
    result = await handler.handle_RCPT(None, MockSession(), envelope, "user@wrong.com", [])
    assert "550" in result


async def test_handle_rcpt_accepts_correct_domain(handler):
    from aiosmtpd.smtp import Envelope

    envelope = Envelope()
    result = await handler.handle_RCPT(None, MockSession(), envelope, "user@tempinbox.dev", [])
    assert "250" in result


async def test_handle_data_blacklist_hard_block(handler_with_redis, session_factory, db_session):
    entry = BlacklistEntry(pattern="blocked@evil.com", block_type="hard", is_active=True)
    db_session.add(entry)
    await db_session.commit()

    raw_email = (
        b"From: blocked@evil.com\r\nTo: user@tempinbox.dev\r\nSubject: Blocked\r\n\r\nBlocked"
    )
    envelope = MockEnvelope(
        mail_from="blocked@evil.com",
        rcpt_tos=["user@tempinbox.dev"],
        content=raw_email,
    )
    result = await handler_with_redis.handle_DATA(None, MockSession(), envelope)
    assert "550" in result


async def test_handle_data_blacklist_soft_block(handler_with_redis, session_factory, db_session):
    entry = BlacklistEntry(pattern="spammer@shady.com", block_type="soft", is_active=True)
    db_session.add(entry)
    await db_session.commit()

    raw_email = (
        b"From: spammer@shady.com\r\n"
        b"To: user@tempinbox.dev\r\n"
        b"Subject: Soft blocked\r\n"
        b"\r\n"
        b"Soft blocked"
    )
    envelope = MockEnvelope(
        mail_from="spammer@shady.com",
        rcpt_tos=["user@tempinbox.dev"],
        content=raw_email,
    )
    result = await handler_with_redis.handle_DATA(None, MockSession(), envelope)
    assert "450" in result


async def test_handle_data_multi_recipient(handler, session_factory):
    raw_email = (
        b"From: sender@example.com\r\n"
        b"To: a@tempinbox.dev, b@tempinbox.dev\r\n"
        b"Subject: Multi\r\n"
        b"\r\n"
        b"Hello"
    )
    envelope = MockEnvelope(
        mail_from="sender@example.com",
        rcpt_tos=["a@tempinbox.dev", "b@tempinbox.dev"],
        content=raw_email,
    )
    result = await handler.handle_DATA(None, MockSession(), envelope)
    assert "250" in result

    async with session_factory() as db:
        a_msgs = (
            (await db.execute(select(Message).where(Message.recipient == "a@tempinbox.dev")))
            .scalars()
            .all()
        )
        b_msgs = (
            (await db.execute(select(Message).where(Message.recipient == "b@tempinbox.dev")))
            .scalars()
            .all()
        )
        assert len(a_msgs) >= 1
        assert len(b_msgs) >= 1


async def test_handle_data_string_content(handler, session_factory):
    raw_email = (
        "From: sender@example.com\r\n"
        "To: user@tempinbox.dev\r\n"
        "Subject: String Content\r\n"
        "\r\n"
        "Hello as string"
    )
    envelope = MockEnvelope(
        mail_from="sender@example.com",
        rcpt_tos=["user@tempinbox.dev"],
        content=raw_email,
    )
    result = await handler.handle_DATA(None, MockSession(), envelope)
    assert "250" in result

    async with session_factory() as db:
        msgs = (
            (await db.execute(select(Message).where(Message.recipient == "user@tempinbox.dev")))
            .scalars()
            .all()
        )
        assert len(msgs) >= 1
        assert msgs[-1].subject == "String Content"


async def test_handle_rcpt_case_insensitive_domain(handler):
    from aiosmtpd.smtp import Envelope

    envelope = Envelope()
    result = await handler.handle_RCPT(None, MockSession(), envelope, "USER@TEMPINBOX.DEV", [])
    assert "250" in result


async def test_handle_rcpt_no_at_sign(handler):
    from aiosmtpd.smtp import Envelope

    envelope = Envelope()
    result = await handler.handle_RCPT(None, MockSession(), envelope, "noatsign", [])
    assert "550" in result
