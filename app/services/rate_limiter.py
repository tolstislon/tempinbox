"""Redis-based sliding-window rate limiter."""

import time

from redis.asyncio import Redis


async def check_rate_limit(
    redis: Redis,
    identifier: str,
    limit: int,
    window_seconds: int = 60,
) -> tuple[bool, int, int]:
    """Check rate limit using a Redis sorted-set sliding window.

    Returns (allowed, remaining, retry_after_seconds).
    """
    key = f"ratelimit:{identifier}"
    now = time.time()
    window_start = now - window_seconds

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {f"{now}": now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 1)
    results = await pipe.execute()

    count = results[2]

    if count > limit:
        # Remove the entry we just added
        await redis.zrem(key, f"{now}")
        # Compute retry after
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        retry_after = max(1, int(oldest[0][1] + window_seconds - now) + 1) if oldest else 1
        return False, 0, retry_after

    remaining = limit - count
    return True, remaining, 0


async def check_and_record_admin_attempt(
    redis: Redis,
    ip: str,
    *,
    max_attempts: int = 5,
    window_seconds: int = 300,
) -> bool:
    """Atomically increment and check admin auth failure counter.

    Returns True if the IP has exceeded the threshold (request should be blocked).
    """
    key = f"admin_auth_fail:{ip}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return count > max_attempts


async def reset_admin_auth_counter(redis: Redis, ip: str) -> None:
    """Reset the admin auth failure counter on successful authentication."""
    await redis.delete(f"admin_auth_fail:{ip}")
