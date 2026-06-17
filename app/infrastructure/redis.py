from typing import Protocol

from redis.asyncio import Redis


class RedisClient(Protocol):
    async def get(self, name: str) -> str | None: ...

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> object: ...

    async def incr(self, name: str) -> int: ...

    async def expire(self, name: str, time: int) -> bool: ...

    async def ttl(self, name: str) -> int: ...


def create_redis(url: str) -> Redis:
    return Redis.from_url(url, encoding="utf-8", decode_responses=True)


async def close_redis(client: Redis) -> None:
    await client.aclose()
