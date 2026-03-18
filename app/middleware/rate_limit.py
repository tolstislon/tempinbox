"""HTTP middleware that enforces per-key rate limiting via Redis."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from app.api.deps import get_client_ip
from app.services.keys import hash_key
from app.services.rate_limiter import check_rate_limit


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests exceeding the sliding-window rate limit."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in ("/health", "/docs", "/openapi.json"):
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:
            return await call_next(request)

        settings = request.app.state.settings

        api_key = request.headers.get("x-api-key")
        if api_key:
            key_hash = hash_key(api_key, secret=settings.api_key_hmac_secret)
            identifier = key_hash[:16]

            # Check per-key rate limit override from Redis cache
            cached_limit = await redis.get(f"api_key_limit:{key_hash}")
            limit = int(cached_limit) if cached_limit else settings.rate_limit_per_minute
        else:
            identifier = get_client_ip(request)
            limit = settings.rate_limit_per_minute

        allowed, remaining, retry_after = await check_rate_limit(
            redis,
            identifier,
            limit,
        )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
