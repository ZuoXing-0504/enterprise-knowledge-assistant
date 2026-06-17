import logging
from dataclasses import dataclass
from uuid import UUID

from app.infrastructure.redis import RedisClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RedisRateLimiter:
    def __init__(self, redis: RedisClient | None) -> None:
        self.redis = redis

    async def check(
        self,
        *,
        scope: str,
        user_id: UUID,
        limit: int,
        window_seconds: int,
    ) -> RateLimitResult:
        if self.redis is None:
            return RateLimitResult(True, limit, 0)

        key = f"rate-limit:{scope}:{user_id}"
        try:
            current = await self.redis.incr(key)
            if current == 1:
                await self.redis.expire(key, window_seconds)
            ttl = await self.redis.ttl(key)
        except Exception as exc:
            logger.warning(
                "rate_limit_redis_failed scope=%s exception_type=%s",
                scope,
                type(exc).__name__,
            )
            return RateLimitResult(True, limit, 0)

        retry_after = ttl if ttl > 0 else window_seconds
        return RateLimitResult(
            allowed=current <= limit,
            remaining=max(0, limit - current),
            retry_after_seconds=retry_after if current > limit else 0,
        )
