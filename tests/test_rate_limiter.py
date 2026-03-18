from app.services.rate_limiter import (
    check_and_record_admin_attempt,
    check_rate_limit,
    reset_admin_auth_counter,
)


async def test_allows_within_limit(redis):
    for _ in range(5):
        allowed, remaining, _ = await check_rate_limit(redis, "test-key", limit=5)
        assert allowed is True

    assert remaining == 0


async def test_blocks_over_limit(redis):
    for _ in range(5):
        await check_rate_limit(redis, "test-key2", limit=5)

    allowed, remaining, retry_after = await check_rate_limit(redis, "test-key2", limit=5)
    assert allowed is False
    assert remaining == 0
    assert retry_after > 0


async def test_different_identifiers(redis):
    for _ in range(5):
        await check_rate_limit(redis, "key-a", limit=5)

    allowed, _, _ = await check_rate_limit(redis, "key-b", limit=5)
    assert allowed is True


async def test_admin_brute_force_under_threshold(redis):
    ip = "192.168.1.100"
    for _ in range(5):
        blocked = await check_and_record_admin_attempt(redis, ip)
        assert blocked is False


async def test_admin_brute_force_over_threshold(redis):
    ip = "192.168.1.101"
    for _ in range(5):
        await check_and_record_admin_attempt(redis, ip)

    blocked = await check_and_record_admin_attempt(redis, ip)
    assert blocked is True


async def test_admin_attempt_sets_ttl(redis):
    ip = "192.168.1.102"
    await check_and_record_admin_attempt(redis, ip)

    ttl = await redis.ttl(f"admin_auth_fail:{ip}")
    assert ttl > 0


async def test_admin_brute_force_different_ips(redis):
    ip_a = "10.0.0.1"
    ip_b = "10.0.0.2"

    for _ in range(6):
        await check_and_record_admin_attempt(redis, ip_a)

    blocked_a = await check_and_record_admin_attempt(redis, ip_a)
    blocked_b = await check_and_record_admin_attempt(redis, ip_b)
    assert blocked_a is True
    assert blocked_b is False


async def test_reset_admin_auth_counter(redis):
    ip = "192.168.1.200"
    for _ in range(6):
        await check_and_record_admin_attempt(redis, ip)

    assert await check_and_record_admin_attempt(redis, ip) is True

    await reset_admin_auth_counter(redis, ip)
    assert await check_and_record_admin_attempt(redis, ip) is False
