"""On-disk outbox for observations.

Every observation is written here first and deleted only after the server confirms it,
so nothing is lost while the server is unreachable. The outbox is a bounded cache:
when it exceeds ``max_bytes`` the oldest observations are evicted.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from agent.uploader.client import ApiClient

log = logging.getLogger(__name__)


class DiskQueue:
    def __init__(self, root: Path, max_bytes: int = 1024 * 1024 * 1024):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.evicted = 0

    def put(self, metadata: dict, frames: list[tuple[str, bytes]]) -> Path:
        with self._lock:
            item = self.root / f"{time.time_ns():020d}_{uuid.uuid4().hex[:8]}"
            tmp = item.with_suffix(".tmp")
            tmp.mkdir()
            for name, data in frames:
                (tmp / name).write_bytes(data)
            (tmp / "meta.json").write_text(
                json.dumps({"metadata": metadata, "frames": [n for n, _ in frames]})
            )
            tmp.rename(item)  # atomic: half-written items are never picked up
            self._evict_if_needed()
            return item

    def items(self) -> list[Path]:
        return sorted(p for p in self.root.iterdir() if p.is_dir() and p.suffix != ".tmp")

    def load(self, item: Path) -> tuple[dict, list[tuple[str, bytes]]]:
        meta = json.loads((item / "meta.json").read_text())
        return meta["metadata"], [(n, (item / n).read_bytes()) for n in meta["frames"]]

    def remove(self, item: Path) -> None:
        shutil.rmtree(item, ignore_errors=True)

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def _evict_if_needed(self) -> None:
        items = self.items()
        total = self.size_bytes()
        while total > self.max_bytes and len(items) > 1:
            oldest = items.pop(0)
            total -= sum(f.stat().st_size for f in oldest.rglob("*") if f.is_file())
            self.remove(oldest)
            self.evicted += 1
            log.warning("Outbox full, evicted %s", oldest.name)


class Uploader(threading.Thread):
    """Background thread draining the outbox in order, with exponential backoff."""

    def __init__(self, queue: DiskQueue, client: ApiClient):
        super().__init__(daemon=True, name="uploader")
        self.queue = queue
        self.client = client
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.uploaded = 0
        self.failures = 0

    def run(self) -> None:
        backoff = 1.0
        while not self.stopping.is_set():
            ok = self._drain()
            backoff = 1.0 if ok else min(backoff * 2, 30.0)
            self.wake.wait(timeout=backoff if not ok else 5.0)
            self.wake.clear()

    def _drain(self) -> bool:
        for item in self.queue.items():
            try:
                metadata, frames = self.queue.load(item)
            except (OSError, ValueError, KeyError):
                log.exception("Corrupt outbox item %s, dropping", item.name)
                self.queue.remove(item)
                continue
            try:
                self.client.post_observation(metadata, frames)
            except Exception as exc:  # network down, server error...
                self.failures += 1
                log.warning("Upload failed (%s); %d item(s) queued", exc, len(self.queue.items()))
                return False
            self.queue.remove(item)
            self.uploaded += 1
            log.info("Uploaded observation %s (%s)", item.name, metadata["observation_type"])
        return True

    def flush(self, timeout: float) -> bool:
        """Wait until the outbox is empty or ``timeout`` elapses."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.queue.items():
                return True
            self.wake.set()
            time.sleep(0.5)
        return not self.queue.items()

    def stop(self) -> None:
        self.stopping.set()
        self.wake.set()
