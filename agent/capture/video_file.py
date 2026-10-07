from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from agent.capture.base import CaptureSource


class VideoFileSource(CaptureSource):
    """Replays a video file as if it were the device camera (for testing without hardware).

    Timestamps are ``start_ts + position in video``. With ``realtime`` the replay is
    paced like a live camera; otherwise it runs as fast as decoding allows.
    """

    def __init__(self, path: str | Path, start_ts: float | None = None, realtime: bool = False):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        self.start_ts = start_ts if start_ts is not None else time.time()
        self.realtime = realtime
        self._pos = 0

    def frames(self, interval: float) -> Iterator[tuple[float, np.ndarray]]:
        wall_start = time.time()
        next_sample = 0.0
        while self.cap.grab():
            offset = self._pos / self.fps
            self._pos += 1
            if offset < next_sample:
                continue
            ok, frame = self.cap.retrieve()
            if not ok:
                continue
            next_sample = offset + interval
            if self.realtime:
                delay = offset - (time.time() - wall_start)
                if delay > 0:
                    time.sleep(delay)
            yield self.start_ts + offset, frame

    def progress(self) -> float | None:
        return min(1.0, self._pos / self.total) if self.total else None

    def close(self) -> None:
        self.cap.release()
