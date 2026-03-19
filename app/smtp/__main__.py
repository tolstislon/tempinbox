"""Standalone SMTP server entry point (python -m app.smtp)."""

import asyncio

import structlog

from app.config import Settings
from app.database import create_engine, create_session_factory
from app.logging import setup_logging
from app.smtp.server import create_smtp_server

logger = structlog.get_logger()


async def main() -> None:
    """Start the SMTP server and block until interrupted."""
    setup_logging(json_format=True)
    settings = Settings()

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    smtp_server = await create_smtp_server(session_factory, settings)

    await logger.ainfo("SMTP server started", host=settings.smtp_host, port=settings.smtp_port)

    try:
        await asyncio.Event().wait()
    finally:
        await smtp_server.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
