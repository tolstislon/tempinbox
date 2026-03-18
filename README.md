# TempInbox

Disposable email service with a built-in SMTP receiver and REST API.

## Overview

TempInbox accepts emails via SMTP, stores them in PostgreSQL, and exposes them through a FastAPI-based REST API. It is designed for testing, CI pipelines, and development environments where you need to programmatically receive and inspect emails without a real mailbox.

## Features

- **SMTP receiver** — accepts emails on configurable domains via aiosmtpd
- **REST API** — list, search, and retrieve messages; paginated with filtering
- **API key authentication** — SHA-256 hashed keys with optional domain restrictions and expiry
- **Rate limiting** — Redis-based sliding-window rate limiter with per-key overrides
- **Auto-cleanup** — background task deletes messages older than a configurable TTL
- **Sender blacklist** — pattern-based blocking (hard reject / soft temp-fail) with fnmatch
- **Admin API** — manage keys, blacklist entries, and messages via master-key auth
- **Docker-ready** — multi-stage Dockerfile and docker-compose for one-command deployment

## Quick Start (local)

```bash
# 1. Copy and edit environment file
cp .env.example .env
# Edit .env — set TEMPINBOX_MASTER_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD

# 2. Start all services (migrations run automatically)
docker compose up -d
```

The API is available at `https://localhost` (via Caddy) and the SMTP server at `localhost:25`.

## Production Deployment

### Prerequisites

- VPS with Docker and Docker Compose
- Public static IPv4 address
- Port 25 (SMTP) open — check with your VPS provider, some block it by default
- Domain name pointed to the VPS

### DNS Setup

Configure the following DNS records for your domain (e.g., `api.example.com`):

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `api.example.com` | `<VPS_IP>` | 300 |
| MX | `example.com` | `10 api.example.com` | 300 |
| TXT (SPF) | `example.com` | `v=spf1 -all` | 300 |
| TXT (DMARC) | `_dmarc.example.com` | `v=DMARC1; p=reject; rua=mailto:admin@example.com` | 300 |

> **SPF and DMARC are mandatory.** TempInbox is a receive-only service. `v=spf1 -all` explicitly states that no one is authorized to send email from your domain. DMARC `p=reject` enforces this.

Also configure a **PTR (rDNS) record** for your VPS IP to point back to `api.example.com` (usually done in VPS provider's dashboard).

### Deploy Steps

```bash
# 1. Clone and configure
git clone <repo-url> && cd tempinbox
cp .env.example .env

# 2. Generate secure credentials
sed -i "s/change-me-to-a-secure-random-string/$(openssl rand -hex 32)/" .env
sed -i "s/change-me-to-a-secure-password/$(openssl rand -hex 24)/" .env
sed -i "s/change-me-to-a-different-secure-password/$(openssl rand -hex 24)/" .env

# 3. Set your domain and SMTP domains
# Edit .env:
#   TEMPINBOX_DOMAIN=api.example.com
#   TEMPINBOX_SMTP_DOMAINS=["example.com"]

# 4. Start (migrations run automatically on boot)
docker compose up -d
```

### VPS Requirements

**Minimum (up to ~1,000 emails/day):** 1 vCPU, 2 GB RAM, 20 GB SSD

**Recommended (up to ~10,000 emails/day):** 2 vCPU, 2 GB RAM, 40 GB SSD

Providers with port 25 open: Hetzner Cloud, OVH/Kimsufi, Contabo, Vultr (requires request).

## Development Setup

```bash
# Install dependencies (requires uv)
uv sync --dev

# Start Postgres and Redis
docker compose -f docker-compose.dev.yml up -d

# Run migrations
TEMPINBOX_MASTER_KEY=dev uv run alembic upgrade head

# Start the dev server
TEMPINBOX_MASTER_KEY=dev uv run uvicorn app.main:create_app --factory --reload
```

## Configuration

All settings are configured via environment variables with the `TEMPINBOX_` prefix.

| Variable | Default | Description |
|---|---|---|
| `TEMPINBOX_DATABASE_URL` | `postgresql+asyncpg://tempinbox:tempinbox@localhost:5432/tempinbox` | Async PostgreSQL connection string |
| `TEMPINBOX_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `TEMPINBOX_MASTER_KEY` | *(required)* | Secret key for admin endpoints |
| `TEMPINBOX_SMTP_HOST` | `0.0.0.0` | SMTP listen address |
| `TEMPINBOX_SMTP_PORT` | `2525` | SMTP listen port |
| `TEMPINBOX_SMTP_DOMAINS` | `["tempinbox.dev"]` | Accepted email domains |
| `TEMPINBOX_API_KEY_PREFIX` | `tempinbox_` | Prefix for generated API keys |
| `TEMPINBOX_API_KEY_LENGTH` | `48` | Length of generated API keys |
| `TEMPINBOX_MESSAGE_TTL_HOURS` | `72` | Auto-delete messages older than this |
| `TEMPINBOX_CLEANUP_INTERVAL_MINUTES` | `30` | How often the cleanup task runs |
| `TEMPINBOX_MAX_EMAIL_SIZE` | `10485760` | Maximum email size in bytes (10 MB) |
| `TEMPINBOX_RATE_LIMIT_PER_MINUTE` | `60` | Default rate limit per API key |

## API Reference

### Public API (`/api/v1`) — requires `X-API-Key` header

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/inbox/{email}` | List messages (paginated, filterable) |
| GET | `/api/v1/inbox/{email}/search` | Full-text search in subject/body |
| GET | `/api/v1/inbox/{email}/stats` | Inbox aggregate statistics |
| GET | `/api/v1/message/{message_id}` | Get full message with body and headers |
| GET | `/api/v1/rate-limit` | Current rate limit info for your key |
| GET | `/api/v1/key-info` | Metadata about your API key |

### Admin API (`/admin`) — requires `X-Master-Key` header

| Method | Endpoint | Description |
|---|---|---|
| POST | `/admin/keys` | Create a new API key |
| GET | `/admin/keys` | List all API keys |
| GET | `/admin/keys/{key_id}` | Get a single API key |
| PATCH | `/admin/keys/{key_id}` | Update an API key |
| DELETE | `/admin/keys/{key_id}` | Deactivate an API key |
| POST | `/admin/blacklist` | Add a blacklist entry |
| GET | `/admin/blacklist` | List all blacklist entries |
| PATCH | `/admin/blacklist/{entry_id}` | Update a blacklist entry |
| DELETE | `/admin/blacklist/{entry_id}` | Delete a blacklist entry |
| POST | `/admin/blacklist/import` | Bulk-import blacklist patterns |
| DELETE | `/admin/messages/old` | Delete messages older than N days |
| DELETE | `/admin/inbox/{email}` | Clear all messages for an address |
| GET | `/admin/stats` | System-wide statistics |

### Health Check

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Database and Redis connectivity check |

## Authentication

- **Public endpoints** require an `X-API-Key` header. Keys are created via the admin API and stored as SHA-256 hashes. Keys can have domain restrictions, rate limit overrides, and expiry dates.
- **Admin endpoints** require an `X-Master-Key` header matching the `TEMPINBOX_MASTER_KEY` environment variable.

## SMTP

The built-in SMTP server (powered by aiosmtpd) listens internally on port 2525. In production, Docker maps external port 25 (standard SMTP) to internal 2525 — configurable via `TEMPINBOX_SMTP_EXTERNAL_PORT` in `.env`. It only accepts mail for domains listed in `TEMPINBOX_SMTP_DOMAINS`. Messages from blacklisted senders are rejected (hard block → 550) or temp-failed (soft block → 450).

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run with coverage
uv run coverage run -m pytest tests/ -v
uv run coverage report
```

Tests use [testcontainers](https://testcontainers-python.readthedocs.io/) to spin up real PostgreSQL and Redis instances — no mocks.

## License

MIT
