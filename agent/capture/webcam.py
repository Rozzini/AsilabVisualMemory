from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator

import cv2
import numpy as np

from agent.capture.base import CaptureSource

log = logging.getLogger(__name__)


class WebcamSource(CaptureSource):
    def __init__(self, index: int = 0, width: int = 1280, height: int = 720, warmup_s: float = 1.5):
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            hint = {
                "darwin": "allow camera access for your terminal in System Settings → Privacy & Security → Camera",
                "linux": "check /dev/video* exists and your user is in the 'video' group",
            }.get(sys.platform, "check no other app is using the camera")
            raise RuntimeError(f"Cannot open webcam #{index}: {hint}. Try --webcam 1 for another camera.")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.warmup_s = warmup_s

    def frames(self, interval: float) -> Iterator[tuple[float, np.ndarray]]:
        # Let auto-exposure / white balance settle before the baseline frame.
        start = time.time()
        while time.time() - start < self.warmup_s:
            self.cap.grab()

        next_sample = 0.0
        failures = 0
        while True:
            # grab() keeps the driver queue fresh without decoding; only decode sampled frames.
            if not self.cap.grab():
                failures += 1
                if failures > 50:
                    raise RuntimeError("Webcam stopped delivering frames")
                time.sleep(0.05)
                continue
            failures = 0
            now = time.time()
            if now < next_sample:
                continue
            ok, frame = self.cap.retrieve()
            if not ok:
                continue
            next_sample = now + interval
            yield now, frame

    def close(self) -> None:
        self.cap.release()
