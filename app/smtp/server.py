"""SMTP server handler that receives emails and stores them in the database."""

import asyncio

import structlog
from aiosmtpd.smtp import SMTP as SMTPProtocol
from aiosmtpd.smtp import Envelope, Session
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.tables import Message
from app.services.blacklist import check_blacklist
from app.smtp.parser import parse_email

logger = structlog.get_logger()

MAX_RECIPIENTS = 10


class TempInboxHandler:
    """aiosmtpd handler that validates domains, checks blacklists, and persists messages."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        redis: Redis | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.redis = redis

    async def handle_RCPT(
        self,
        server: SMTPProtocol,
        session: Session,
        envelope: Envelope,
        address: str,
        rcpt_options: list[str],
    ) -> str:
        """Accept the recipient only if the domain is in the allowed list."""
        domain = address.rsplit("@", 1)[-1] if "@" in address else ""
        if domain.lower() not in [d.lower() for d in self.settings.smtp_domains]:
            return "550 Domain not accepted"
        if len(envelope.rcpt_tos) >= MAX_RECIPIENTS:
            return "452 Too many recipients"
        envelope.rcpt_tos.append(address.lower())
        return "250 OK"

    async def handle_DATA(
        self,
        server: SMTPProtocol,
        session: Session,
        envelope: Envelope,
    ) -> str:
        """Parse the email, check blacklist, and store messages for each recipient."""
        raw_data = envelope.content
        if isinstance(raw_data, str):
            raw_data = raw_data.encode()

        if len(raw_data) > self.settings.max_email_size:
            return "552 Message too large"

        sender = envelope.mail_from or ""

        async with self.session_factory() as db:
            # Check blacklist
            block_type = await check_blacklist(db, sender, redis=self.redis)
            if block_type == "hard":
                return "550 No such mailbox"
            if block_type == "soft":
                return "450 Mailbox temporarily unavailable"

            for recipient in envelope.rcpt_tos:
                recipient = recipient.lower()
                try:
                    parsed = parse_email(raw_data, sender, recipient)
                except Exception:
                    await logger.aexception(
                        "Failed to parse email", sender=sender, recipient=recipient
                    )
                    return "550 Message rejected"
                msg = Message(
                    sender=parsed.sender,
                    recipient=parsed.recipient,
                    subject=parsed.subject,
                    body_text=parsed.body_text,
                    body_html=parsed.body_html,
                    raw_headers=parsed.raw_headers,
                    size_bytes=parsed.size_bytes,
                    domain=parsed.domain,
                )
                db.add(msg)

            await db.commit()

        await logger.ainfo(
            "Message accepted",
            sender=sender,
            recipients=envelope.rcpt_tos,
            size=len(raw_data),
        )
        return "250 Message accepted"


class SMTPServer:
    """Runs aiosmtpd in the same asyncio event loop as FastAPI."""

    def __init__(
        self,
        handler: TempInboxHandler,
        hostname: str,
        port: int,
    ) -> None:
        self.handler = handler
        self.hostname = hostname
        self.port = port
        self.server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start the SMTP server in the current event loop."""
        self.server = await asyncio.get_running_loop().create_server(
            lambda: SMTPProtocol(self.handler),
            self.hostname,
            self.port,
        )

    async def stop(self) -> None:
        """Stop the SMTP server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()


async def create_smtp_server(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    redis: Redis | None = None,
) -> SMTPServer:
    """Create and start an SMTP server in the current event loop."""
    handler = TempInboxHandler(session_factory, settings, redis=redis)
    server = SMTPServer(handler, settings.smtp_host, settings.smtp_port)
    await server.start()
    return server
