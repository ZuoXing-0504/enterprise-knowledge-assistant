import hashlib
import json
import logging

from app.infrastructure.redis import RedisClient

logger = logging.getLogger(__name__)


class EmbeddingCache:
    def __init__(
        self,
        redis: RedisClient | None,
        *,
        ttl_seconds: int,
    ) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def get(self, *, model_name: str, text: str) -> list[float] | None:
        if self.redis is None or self.ttl_seconds == 0:
            return None
        try:
            value = await self.redis.get(self._key(model_name, text))
            if value is None:
                return None
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                return None
            return [float(item) for item in parsed]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        except Exception as exc:
            logger.warning(
                "embedding_cache_read_failed exception_type=%s",
                type(exc).__name__,
            )
            return None

    async def set(
        self,
        *,
        model_name: str,
        text: str,
        embedding: list[float],
    ) -> None:
        if self.redis is None or self.ttl_seconds == 0:
            return
        try:
            await self.redis.set(
                self._key(model_name, text),
                json.dumps(embedding, separators=(",", ":")),
                ex=self.ttl_seconds,
            )
        except Exception as exc:
            logger.warning(
                "embedding_cache_write_failed exception_type=%s",
                type(exc).__name__,
            )

    @staticmethod
    def _key(model_name: str, text: str) -> str:
        digest = hashlib.sha256(f"{model_name}\0{text}".encode()).hexdigest()
        return f"embedding-cache:{digest}"
