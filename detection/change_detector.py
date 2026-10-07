"""Scene-event detector.

Cheap enough for a 2-core device: every sample is shrunk to ~160 px grayscale and
compared with two references:

* ``motion``      – vs the previous sample (is something moving right now?)
* ``scene_delta`` – vs the last emitted keyframe (has the scene changed since?)

An event starts when the scene departs from the last keyframe. It is closed when the
scene has been still for ``settle_samples`` samples, or checkpointed every
``checkpoint_seconds`` while activity continues. What gets emitted:

* ``baseline``      – the first frame (the server inventories the scene)
* ``visual_change`` – the scene settled in a different state (object moved, light off,
                      person sat down, camera moved...)
* ``activity``      – something happened but the scene ended as it was (someone walked
                      through, waved an object), or a checkpoint during long activity

Thresholds adapt to the camera: the noise floor is the median frame-to-frame motion of
the recent past, so a person sitting in view or a noisy sensor counts as "still" while
real actions stand out. Only noise-level blips are discarded on the device; the VLM on
the server decides what is worth remembering.

The detector stores no full-resolution frames; it only reports timestamps. The caller
keeps compressed frames in a RollingBuffer and fetches evidence by timestamp.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Literal

import cv2
import numpy as np

EventType = Literal["baseline", "visual_change", "activity"]


@dataclass
class DetectorConfig:
    analysis_width: int = 160
    blur_kernel: int = 5
    # per-pixel intensity difference that counts as "changed"
    pixel_threshold: int = 25
    # The ratios below are fractions of changed pixels in the analysis frame. They are lower
    # bounds: the effective thresholds rise with the camera's noise floor.
    # vs the last keyframe: starts an event
    trigger_ratio: float = 0.005
    # settled scene vs last keyframe: needed for a visual_change
    change_ratio: float = 0.003
    # vs the previous sample: "still" if below max(still_ratio, noise × still_noise_factor)
    still_ratio: float = 0.004
    still_ratio_max: float = 0.05
    still_noise_factor: float = 2.5
    # peak motion needed to report an activity whose scene ended unchanged
    activity_ratio: float = 0.02
    # consecutive still samples required to consider the scene settled
    settle_samples: int = 2
    # emit a checkpoint at this interval while activity continues
    checkpoint_seconds: float = 10.0
    # number of recent quiet samples used for the noise floor, and its upper bound
    # (about the micro-movement of a person sitting in view)
    noise_window: int = 30
    noise_cap: float = 0.02
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
    forced: bool = False  # True for checkpoints during continuing activity


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
    ACTIVE = "active"

    def __init__(self, config: DetectorConfig | None = None):
        self.cfg = config or DetectorConfig()
        self.stats = DetectorStats()
        self.reset()

    def reset(self) -> None:
        self.state = self.IDLE
        self._reference: np.ndarray | None = None
        self._prev: np.ndarray | None = None
        self._prev_ts: float | None = None
        self._motions: deque[float] = deque(maxlen=self.cfg.noise_window)
        self._segment_ts = 0.0
        self._before_ts: float | None = None
        self._peak_ts: float | None = None
        self._peak_motion = 0.0
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

    # --- adaptive thresholds -------------------------------------------------

    @property
    def noise_floor(self) -> float:
        if not self._motions:
            return 0.0
        return min(statistics.median(self._motions), self.cfg.noise_cap)

    def _thresholds(self) -> tuple[float, float, float, float]:
        cfg, noise = self.cfg, self.noise_floor
        still = min(max(cfg.still_ratio, noise * cfg.still_noise_factor), cfg.still_ratio_max)
        trigger = max(cfg.trigger_ratio, 2 * noise)
        change = max(cfg.change_ratio, 2 * noise)
        activity = max(cfg.activity_ratio, 4 * noise)
        return still, trigger, change, activity

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
        still_thr, trigger_thr, change_thr, activity_thr = self._thresholds()
        if motion <= cfg.still_ratio_max:  # real activity must not raise the noise floor
            self._motions.append(motion)
        event: DetectedEvent | None = None

        if self.state == self.IDLE:
            if delta > trigger_thr:
                self.state = self.ACTIVE
                self.stats.triggers += 1
                self._start_segment(self._prev_ts, ts, motion)
        else:
            if motion > self._peak_motion:
                self._peak_ts, self._peak_motion = ts, motion
            self._still = self._still + 1 if motion < still_thr else 0

            if self._still >= cfg.settle_samples:
                if delta > change_thr:
                    event = self._emit("visual_change", ts, delta, cur)
                elif self._peak_motion > activity_thr:
                    event = self._emit("activity", ts, delta, cur)
                else:
                    self.stats.discarded += 1
                self._reference = cur
                self.state = self.IDLE
            elif ts - self._segment_ts >= cfg.checkpoint_seconds:
                if delta > change_thr or self._peak_motion > activity_thr:
                    event = self._emit("activity", ts, delta, cur, forced=True)
                    self._reference = cur
                # activity goes on: the current frame starts the next segment
                self._start_segment(ts, ts, 0.0)

        self._prev, self._prev_ts = cur, ts
        return event

    def _start_segment(self, before_ts: float | None, ts: float, motion: float) -> None:
        self._segment_ts = ts
        self._before_ts = before_ts
        self._peak_ts, self._peak_motion = ts, motion
        self._still = 0

    def _emit(
        self, type_: EventType, ts: float, delta: float, cur: np.ndarray, forced: bool = False
    ) -> DetectedEvent:
        self.stats.emitted += 1
        ref = self._reference
        # Global measurements the VLM is bad at noticing on its own (see backend vision hints):
        # overall brightness (lights on/off) and a whole-image shift (the camera was moved).
        shift, explained = self._view_shift(ref, cur, delta)
        return DetectedEvent(
            type=type_,
            start_ts=self._segment_ts,
            end_ts=ts,
            before_ts=self._before_ts,
            peak_ts=self._peak_ts,
            after_ts=ts,
            scores={
                "final_delta": round(delta, 4),
                "peak_motion": round(self._peak_motion, 4),
                "noise_floor": round(self.noise_floor, 4),
                "brightness_before": round(float(ref.mean()) / 255, 3),
                "brightness_after": round(float(cur.mean()) / 255, 3),
                "view_shift": round(shift, 3),
                "view_shift_explains": round(explained, 2),
            },
            forced=forced,
        )

    def _view_shift(self, ref: np.ndarray, cur: np.ndarray, delta: float) -> tuple[float, float]:
        """Whole-image shift between keyframe and current frame (fraction of the width), and how
        much of the change it explains (0..1). A camera pan is explained almost entirely by the
        shift; lighting changes or people moving are not, even if phase correlation reports one."""
        (dx, dy), _ = cv2.phaseCorrelate(ref.astype(np.float32), cur.astype(np.float32))
        h, w = cur.shape
        if np.hypot(dx, dy) < 2 or delta <= 0:
            return 0.0, 0.0
        m = np.float32([[1, 0, dx], [0, 1, dy]])
        moved = cv2.warpAffine(ref, m, (w, h))
        overlap = cv2.warpAffine(np.ones_like(ref), m, (w, h)) > 0
        if overlap.sum() < 0.3 * overlap.size:
            return 0.0, 0.0
        diff = cv2.absdiff(moved, cur)[overlap]
        aligned_delta = float(np.count_nonzero(diff > self.cfg.pixel_threshold)) / diff.size
        return float(np.hypot(dx, dy)) / w, max(0.0, 1 - aligned_delta / delta)
