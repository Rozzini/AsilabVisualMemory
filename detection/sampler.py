"""Frame sampling and JPEG encoding helpers shared by device and server pipelines."""

from __future__ import annotations

import cv2
import numpy as np


class FrameSampler:
    """Passes at most one frame per ``interval`` seconds (by frame timestamp)."""

    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._next: float | None = None

    def should_sample(self, ts: float) -> bool:
        if self._next is None or ts >= self._next:
            self._next = ts + self.interval
            return True
        return False


def encode_jpeg(frame: np.ndarray, max_side: int = 1280, quality: int = 80) -> bytes:
    h, w = frame.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()
