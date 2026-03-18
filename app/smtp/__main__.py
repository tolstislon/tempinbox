"""Standalone SMTP server entry point (python -m app.smtp)."""

import asyncio

import structlog

from app.config import Settings
from app.database import create_engine, create_session_factory
from app.logging import setup_logging
from app.smtp.server import create_smtp_controller

logger = structlog.get_logger()


async def main() -> None:
    """Start the SMTP server and block until interrupted."""
    setup_logging(json_format=True)
    settings = Settings()

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    controller = create_smtp_controller(session_factory, settings)
    controller.start()

    await logger.ainfo("SMTP server started", host=settings.smtp_host, port=settings.smtp_port)

    try:
        await asyncio.Event().wait()
    finally:
        controller.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
