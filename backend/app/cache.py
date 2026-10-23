"""Tiny in-memory TTL cache so external APIs are not hit on every browser request."""
import time
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float) -> Any | None:
        hit = self._store.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        return None

    def get_stale(self, key: str) -> tuple[float, Any] | None:
        """Last value regardless of age (used when the upstream is down)."""
        return self._store.get(key)

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)


cache = TTLCache()
