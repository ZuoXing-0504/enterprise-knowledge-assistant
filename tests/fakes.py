import time as time_module


class InMemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, float] = {}

    async def get(self, name: str) -> str | None:
        self._remove_if_expired(name)
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: str,
        *,
        ex: int | None = None,
    ) -> bool:
        self.values[name] = value
        if ex is not None:
            self.expirations[name] = time_module.monotonic() + ex
        return True

    async def incr(self, name: str) -> int:
        self._remove_if_expired(name)
        current = int(self.values.get(name, "0")) + 1
        self.values[name] = str(current)
        return current

    async def expire(self, name: str, time: int) -> bool:
        if name not in self.values:
            return False
        self.expirations[name] = time_module.monotonic() + time
        return True

    async def ttl(self, name: str) -> int:
        self._remove_if_expired(name)
        if name not in self.values:
            return -2
        expires_at = self.expirations.get(name)
        if expires_at is None:
            return -1
        return max(0, round(expires_at - time_module.monotonic()))

    def _remove_if_expired(self, name: str) -> None:
        expires_at = self.expirations.get(name)
        if expires_at is not None and expires_at <= time_module.monotonic():
            self.values.pop(name, None)
            self.expirations.pop(name, None)
