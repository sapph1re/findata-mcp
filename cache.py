"""Simple in-memory TTL cache."""

import time
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with per-key TTL expiration."""

    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        if key in self._store:
            expires_at, value = self._store[key]
            if time.monotonic() < expires_at:
                return value
            del self._store[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self.ttl, value)

    def clear(self) -> None:
        self._store.clear()

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count of evicted keys."""
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]
        return len(expired)
