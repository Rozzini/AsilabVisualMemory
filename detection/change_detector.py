"""Settle-based change detector.

Cheap enough for a 2-core device: every sample is shrunk to ~160 px grayscale and
compared with two references:

* ``motion``      – vs the previous sample (is something moving right now?)
* ``scene_delta`` – vs the last *stable* scene (has the scene changed?)

An event starts when the scene departs from the stable reference and ends once the
scene has been still for ``settle_samples`` samples. Only if the settled scene still
differs from the reference is an event emitted, so a person walking through and
leaving produces nothing, while "keys moved from desk to shelf" produces a clean
before/after pair without a hand in the way.

The detector stores no full-resolution frames; it only reports timestamps. The caller
keeps compressed frames in a RollingBuffer and fetches evidence by timestamp.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

import cv2
import numpy as np

EventType = Literal["baseline", "visual_change"]


@dataclass
class DetectorConfig:
    analysis_width: int = 160
    blur_kernel: int = 5
    # per-pixel intensity difference that counts as "changed"
    pixel_threshold: int = 25
    # Thresholds are fractions of changed pixels in the 160 px analysis frame. Small objects
    # matter (keys are <1% of a typical frame), so they are tuned for recall; the VLM on the
    # server makes the final "is this meaningful?" decision.
    # vs the stable reference: starts an event
    trigger_ratio: float = 0.005
    # vs the previous sample: below this the scene is "still"
    still_ratio: float = 0.002
    # consecutive still samples required to consider the scene settled
    settle_samples: int = 3
    # settled scene vs reference: required to emit (otherwise it was a walk-through)
    change_ratio: float = 0.003
    # force an emit if activity never settles
    max_event_seconds: float = 60.0
    emit_baseline: bool = True


@dataclass
class DetectedEvent:
    type: EventType
    start_ts: float
    end_ts: float
    before_ts: float | None
    peak_ts: float | None
    after_ts: float
    scores: dict = field(default_factory=dict)
    forced: bool = False


@dataclass
class DetectorStats:
    samples: int = 0
    triggers: int = 0
    emitted: int = 0
    discarded: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


class ChangeDetector:
    IDLE = "idle"
    CHANGING = "changing"

    def __init__(self, config: DetectorConfig | None = None):
        self.cfg = config or DetectorConfig()
        self.stats = DetectorStats()
        self.reset()

    def reset(self) -> None:
        self.state = self.IDLE
        self._reference: np.ndarray | None = None
        self._prev: np.ndarray | None = None
        self._prev_ts: float | None = None
        self._start_ts = 0.0
        self._before_ts: float | None = None
        self._peak_ts: float | None = None
        self._peak_motion = 0.0
        self._max_delta = 0.0
        self._still = 0

    # --- image helpers -------------------------------------------------------

    def _prepare(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        width = self.cfg.analysis_width
        height = max(1, round(h * width / w))
        small = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        if small.ndim == 3:
            small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        k = self.cfg.blur_kernel
        return cv2.GaussianBlur(small, (k, k), 0)

    def _changed_ratio(self, a: np.ndarray, b: np.ndarray) -> float:
        diff = cv2.absdiff(a, b)
        return float(np.count_nonzero(diff > self.cfg.pixel_threshold)) / diff.size

    # --- main entry point ----------------------------------------------------

    def process(self, ts: float, frame: np.ndarray) -> DetectedEvent | None:
        """Feed one sampled frame. Returns an event when one completes."""
        cfg = self.cfg
        cur = self._prepare(frame)
        self.stats.samples += 1

        if self._reference is None:
            self._reference = cur
            self._prev, self._prev_ts = cur, ts
            if cfg.emit_baseline:
                self.stats.emitted += 1
                return DetectedEvent("baseline", ts, ts, None, None, ts)
            return None

        motion = self._changed_ratio(cur, self._prev)
        delta = self._changed_ratio(cur, self._reference)
        event: DetectedEvent | None = None

        if self.state == self.IDLE:
            if delta > cfg.trigger_ratio:
                self.state = self.CHANGING
                self.stats.triggers += 1
                self._start_ts = ts
                self._before_ts = self._prev_ts
                self._peak_ts, self._peak_motion = ts, motion
                self._max_delta = delta
                self._still = 0
        else:
            if motion > self._peak_motion:
                self._peak_ts, self._peak_motion = ts, motion
            self._max_delta = max(self._max_delta, delta)
            self._still = self._still + 1 if motion < cfg.still_ratio else 0

            if self._still >= cfg.settle_samples:
                if delta > cfg.change_ratio:
                    event = self._emit(ts, delta, forced=False)
                else:
                    self.stats.discarded += 1
                self._reference = cur
                self.state = self.IDLE
            elif ts - self._start_ts >= cfg.max_event_seconds:
                event = self._emit(ts, delta, forced=True)
                self._reference = cur
                self.state = self.IDLE

        self._prev, self._prev_ts = cur, ts
        return event

    def _emit(self, ts: float, delta: float, forced: bool) -> DetectedEvent:
        self.stats.emitted += 1
        return DetectedEvent(
            type="visual_change",
            start_ts=self._start_ts,
            end_ts=ts,
            before_ts=self._before_ts,
            peak_ts=self._peak_ts,
            after_ts=ts,
            scores={
                "final_delta": round(delta, 4),
                "max_delta": round(self._max_delta, 4),
                "peak_motion": round(self._peak_motion, 4),
            },
            forced=forced,
        )
