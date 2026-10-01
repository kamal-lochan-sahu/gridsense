"""Small thread-safe TTL cache with stale-on-error and single-flight loading."""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Tuple

log = logging.getLogger(__name__)


@dataclass
class _Entry:
    value: Any
    stored_at: float


class TTLCache:
    def __init__(
        self,
        max_stale_seconds: float = 6 * 3600,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._entries: Dict[str, _Entry] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._max_stale = max_stale_seconds
        self._clock = clock

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get_or_load(self, key: str, ttl: float, loader: Callable[[], Any]) -> Tuple[Any, bool]:
        """Return ``(value, is_stale)``.

        Fresh cached values are returned as-is. Otherwise ``loader`` runs once per key
        (concurrent callers wait for it). If the loader fails, a cached value younger than
        ``max_stale_seconds`` is served with ``is_stale=True``; without one the error propagates.
        """
        entry = self._entries.get(key)
        if entry and self._clock() - entry.stored_at < ttl:
            return entry.value, False

        with self._lock_for(key):
            entry = self._entries.get(key)  # another thread may have refreshed it meanwhile
            if entry and self._clock() - entry.stored_at < ttl:
                return entry.value, False
            try:
                value = loader()
            except Exception:
                if entry and self._clock() - entry.stored_at < self._max_stale:
                    log.warning("Refresh of %r failed, serving stale data", key)
                    return entry.value, True
                raise
            self._entries[key] = _Entry(value, self._clock())
            return value, False

    def ages(self) -> Dict[str, float]:
        """Age in seconds of every cached key."""
        now = self._clock()
        return {key: round(now - entry.stored_at, 1) for key, entry in list(self._entries.items())}
