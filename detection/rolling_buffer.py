"""Bounded buffer of recent JPEG-compressed frames, keyed by timestamp."""

from __future__ import annotations

import bisect
from collections import deque


class RollingBuffer:
    def __init__(self, max_seconds: float = 90.0, max_bytes: int = 32 * 1024 * 1024):
        self.max_seconds = max_seconds
        self.max_bytes = max_bytes
        self._items: deque[tuple[float, bytes]] = deque()
        self._bytes = 0

    def add(self, ts: float, jpeg: bytes) -> None:
        self._items.append((ts, jpeg))
        self._bytes += len(jpeg)
        while self._items and (
            ts - self._items[0][0] > self.max_seconds or self._bytes > self.max_bytes
        ):
            _, old = self._items.popleft()
            self._bytes -= len(old)

    def get(self, ts: float | None) -> bytes | None:
        """Frame at ``ts`` or the closest one before it (falls back to the oldest)."""
        if ts is None or not self._items:
            return None
        stamps = [t for t, _ in self._items]
        i = bisect.bisect_right(stamps, ts) - 1
        return self._items[max(i, 0)][1]

    def __len__(self) -> int:
        return len(self._items)

    @property
    def size_bytes(self) -> int:
        return self._bytes
