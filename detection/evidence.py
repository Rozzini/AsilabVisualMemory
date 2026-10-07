from __future__ import annotations

from detection.change_detector import DetectedEvent
from detection.rolling_buffer import RollingBuffer


def evidence_frames(ev: DetectedEvent, buffer: RollingBuffer) -> list[tuple[str, bytes]]:
    """Pick before / mid / after JPEGs for an event from the rolling buffer."""
    if ev.type == "visual_change":
        picks = [("before.jpg", ev.before_ts), ("mid.jpg", ev.peak_ts), ("after.jpg", ev.after_ts)]
    else:
        picks = [("after.jpg", ev.after_ts)]
    frames: list[tuple[str, bytes]] = []
    seen: set[int] = set()
    for name, ts in picks:
        data = buffer.get(ts)
        if data is not None and id(data) not in seen:  # mid may coincide with before/after
            seen.add(id(data))
            frames.append((name, data))
    return frames
