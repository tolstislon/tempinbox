"""Tests for the keys service layer (app/services/keys.py)."""

import hashlib
import hmac

from app.models.tables import ApiKey
from app.schemas.keys import ApiKeyCreate
from app.services.keys import create_api_key, hash_key, validate_api_key

# ---------------------------------------------------------------------------
# hash_key
# ---------------------------------------------------------------------------


class TestHashKey:
    def test_hash_key_sha256(self):
        """Plain SHA-256 hash matches hashlib.sha256 directly."""
        raw = "some-test-key"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert hash_key(raw) == expected

    def test_hash_key_hmac(self):
        """HMAC-SHA256 differs from plain SHA-256."""
        raw = "some-test-key"
        secret = "my-secret"  # noqa: S105
        plain = hash_key(raw)
        hmac_hash = hash_key(raw, secret=secret)

        assert plain != hmac_hash
        expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        assert hmac_hash == expected


# ---------------------------------------------------------------------------
# create_api_key
# ---------------------------------------------------------------------------


class TestCreateApiKey:
    async def test_create_api_key_returns_raw_key(self, db_session):
        """Returned raw key starts with the default prefix."""
        data = ApiKeyCreate(name="k1")
        result = await create_api_key(db_session, data)

        assert result.key.startswith("tempinbox_")
        assert result.name == "k1"
        assert result.id is not None
        assert result.created_at is not None

    async def test_create_api_key_with_hmac(self, db_session):
        """When HMAC secret is provided the stored hash differs from plain SHA-256."""
        data = ApiKeyCreate(name="k-hmac")
        result = await create_api_key(db_session, data, hmac_secret="s3cret")  # noqa: S106

        plain_hash = hashlib.sha256(result.key.encode()).hexdigest()
        stored = await db_session.get(ApiKey, result.id)
        assert stored is not None
        assert stored.key_hash != plain_hash


# ---------------------------------------------------------------------------
# validate_api_key
# ---------------------------------------------------------------------------


class TestValidateApiKey:
    async def test_validate_active_key(self, db_session, test_api_key):
        """An active, non-expired key is returned successfully."""
        raw_key, original = test_api_key
        result = await validate_api_key(db_session, raw_key)

        assert result is not None
        assert result.id == original.id

    async def test_validate_inactive_key_returns_none(self, db_session, inactive_api_key):
        """An inactive key returns None."""
        raw_key, _ = inactive_api_key
        result = await validate_api_key(db_session, raw_key)
        assert result is None

    async def test_validate_expired_key_returns_none(self, db_session, expired_api_key):
        """An expired key returns None."""
        raw_key, _ = expired_api_key
        result = await validate_api_key(db_session, raw_key)
        assert result is None

    async def test_validate_nonexistent_key_returns_none(self, db_session):
        """A completely random key returns None."""
        result = await validate_api_key(db_session, "tempinbox_nonexistent_random_garbage")
        assert result is None

    async def test_validate_increments_counters(self, db_session, test_api_key):
        """Validation bumps total_requests and sets last_used_at."""
        raw_key, original = test_api_key
        assert original.total_requests == 0
        assert original.last_used_at is None

        await validate_api_key(db_session, raw_key)
        await db_session.refresh(original)

        assert original.total_requests == 1
        assert original.last_used_at is not None

    async def test_validate_caches_rate_limit_override(
        self,
        db_session,
        redis,
    ):
        """When a key has rate_limit_override, it gets cached in Redis."""
        data = ApiKeyCreate(name="rate-limited", rate_limit_override=500)
        created = await create_api_key(db_session, data)

        result = await validate_api_key(db_session, created.key, redis=redis)
        assert result is not None

        key_hash_val = hash_key(created.key)
        cached = await redis.get(f"api_key_limit:{key_hash_val}")
        assert cached is not None
        assert int(cached) == 500
