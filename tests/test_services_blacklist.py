import json

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import BlacklistEntry
from app.schemas.keys import BlacklistCreate
from app.services.blacklist import (
    _CACHE_KEY,
    add_entry,
    check_blacklist,
    delete_entry,
)


async def _create_entry(db, pattern, block_type="hard", is_active=True):
    entry = BlacklistEntry(
        pattern=pattern,
        block_type=block_type,
        is_active=is_active,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def test_check_blacklist_exact_match(db_session: AsyncSession):
    await _create_entry(db_session, "spam@evil.com")

    result = await check_blacklist(db_session, "spam@evil.com")
    assert result == "hard"


async def test_check_blacklist_domain_wildcard(db_session: AsyncSession):
    await _create_entry(db_session, "*@evil.com")

    result = await check_blacklist(db_session, "anyone@evil.com")
    assert result == "hard"


async def test_check_blacklist_domain_only(db_session: AsyncSession):
    await _create_entry(db_session, "evil.com")

    result = await check_blacklist(db_session, "user@evil.com")
    assert result == "hard"


async def test_check_blacklist_fnmatch_question_mark(db_session: AsyncSession):
    await _create_entry(db_session, "sp?m@evil.com")

    result = await check_blacklist(db_session, "spam@evil.com")
    assert result == "hard"


async def test_check_blacklist_soft_block(db_session: AsyncSession):
    await _create_entry(db_session, "soft@evil.com", block_type="soft")

    result = await check_blacklist(db_session, "soft@evil.com")
    assert result == "soft"


async def test_check_blacklist_no_match(db_session: AsyncSession):
    await _create_entry(db_session, "spam@evil.com")

    result = await check_blacklist(db_session, "legit@good.com")
    assert result is None


async def test_check_blacklist_case_insensitive(db_session: AsyncSession):
    await _create_entry(db_session, "spam@evil.com")

    result = await check_blacklist(db_session, "SPAM@EVIL.COM")
    assert result == "hard"


async def test_check_blacklist_increments_blocked_count(db_session: AsyncSession):
    entry = await _create_entry(db_session, "counted@evil.com")
    assert entry.blocked_count == 0

    await check_blacklist(db_session, "counted@evil.com")

    await db_session.refresh(entry)
    assert entry.blocked_count == 1


async def test_check_blacklist_inactive_entry_ignored(db_session: AsyncSession):
    await _create_entry(db_session, "inactive@evil.com", is_active=False)

    result = await check_blacklist(db_session, "inactive@evil.com")
    assert result is None


async def test_cache_invalidation_on_add(db_session: AsyncSession, redis: Redis):
    # Populate cache by running a check
    await check_blacklist(db_session, "anyone@test.com", redis=redis)
    assert await redis.get(_CACHE_KEY) is not None

    # add_entry should invalidate the cache
    data = BlacklistCreate(pattern="new@evil.com")
    await add_entry(db_session, data, redis=redis)

    assert await redis.get(_CACHE_KEY) is None


async def test_cache_invalidation_on_delete(db_session: AsyncSession, redis: Redis):
    entry = await _create_entry(db_session, "todelete@evil.com")

    # Populate cache
    await check_blacklist(db_session, "anyone@test.com", redis=redis)
    assert await redis.get(_CACHE_KEY) is not None

    # delete_entry should invalidate the cache
    await delete_entry(db_session, entry.id, redis=redis)

    assert await redis.get(_CACHE_KEY) is None


async def test_cached_blacklist_used(db_session: AsyncSession, redis: Redis):
    await _create_entry(db_session, "cached@evil.com")

    # First call populates the cache
    result = await check_blacklist(db_session, "cached@evil.com", redis=redis)
    assert result == "hard"

    # Verify cache is populated
    cached_raw = await redis.get(_CACHE_KEY)
    assert cached_raw is not None

    entries = json.loads(cached_raw)
    assert len(entries) >= 1
    patterns = [e["pattern"] for e in entries]
    assert "cached@evil.com" in patterns

    # Second call should use cache (entry still matched)
    result = await check_blacklist(db_session, "cached@evil.com", redis=redis)
    assert result == "hard"
