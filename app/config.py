"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All TEMPINBOX_* environment variables mapped to typed fields."""

    model_config = {"env_prefix": "TEMPINBOX_"}

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/tempinbox"
    db_pool_size: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # SMTP
    smtp_host: str = "0.0.0.0"
    smtp_port: int = 2525
    smtp_domains: list[str] = ["tempinbox.dev"]

    # Auth
    master_key: str
    api_key_prefix: str = "tempinbox_"
    api_key_length: int = 48
    api_key_hmac_secret: str = ""

    # Messages
    message_ttl_hours: int = 72
    cleanup_interval_minutes: int = 30
    max_email_size: int = 10_485_760  # 10 MB

    # Rate limiting
    rate_limit_per_minute: int = 60

    # Docs
    enable_docs: bool = False
