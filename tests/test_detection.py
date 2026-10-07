import numpy as np

from detection import ChangeDetector, DetectorConfig, FrameSampler, RollingBuffer, encode_jpeg

RNG = np.random.default_rng(0)


def scene(objects=(), noise=3):
    """640x480 gray room with optional filled rectangles (x, y, w, h, value)."""
    img = np.full((480, 640, 3), 120, np.uint8)
    img[300:, :] = 90  # "desk"
    for x, y, w, h, v in objects:
        img[y : y + h, x : x + w] = v
    jitter = RNG.integers(-noise, noise + 1, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + jitter, 0, 255).astype(np.uint8)


KEYS_ON_DESK = (100, 320, 60, 30, 230)
KEYS_ON_SHELF = (450, 120, 60, 30, 230)
PERSON = (200, 50, 200, 430, 30)


def run(frames, cfg=None):
    det = ChangeDetector(cfg)
    events = [e for t, f in enumerate(frames) if (e := det.process(float(t), f))]
    return det, events


def test_first_frame_is_baseline():
    _, events = run([scene()])
    assert [e.type for e in events] == ["baseline"]


def test_static_scene_emits_nothing_after_baseline():
    det, events = run([scene() for _ in range(30)])
    assert [e.type for e in events] == ["baseline"]
    assert det.stats.triggers == 0


def test_object_moved_emits_one_event_after_settling():
    frames = (
        [scene([KEYS_ON_DESK])] * 5
        + [scene([KEYS_ON_DESK, PERSON]), scene([KEYS_ON_SHELF, PERSON])]
        + [scene([KEYS_ON_SHELF]) for _ in range(6)]
    )
    _, events = run(frames)
    changes = [e for e in events if e.type == "visual_change"]
    assert len(changes) == 1
    ev = changes[0]
    assert ev.before_ts == 4.0  # last frame before the person appeared
    assert ev.peak_ts in (5.0, 6.0, 7.0)
    assert ev.after_ts > 7.0
    assert not ev.forced


def test_walk_through_without_change_is_discarded():
    frames = (
        [scene([KEYS_ON_DESK])] * 5
        + [scene([KEYS_ON_DESK, PERSON])] * 2
        + [scene([KEYS_ON_DESK]) for _ in range(6)]
    )
    det, events = run(frames)
    assert [e.type for e in events] == ["baseline"]
    assert det.stats.discarded == 1


def test_continuous_activity_forces_emit():
    cfg = DetectorConfig(max_event_seconds=10)
    frames = [scene()] + [
        scene([(i * 20 % 500, 100, 120, 300, 30 + (i % 2) * 150)]) for i in range(1, 20)
    ]
    _, events = run(frames, cfg)
    forced = [e for e in events if e.forced]
    assert forced and forced[0].end_ts - forced[0].start_ts >= 10


def test_rolling_buffer_bounds_and_lookup():
    buf = RollingBuffer(max_seconds=5)
    for t in range(10):
        buf.add(float(t), bytes([t]) * 10)
    assert len(buf) == 6  # t=4..9
    assert buf.get(7.5) == bytes([7]) * 10
    assert buf.get(0.0) == bytes([4]) * 10  # older than window -> oldest kept
    assert buf.get(None) is None


def test_sampler_and_jpeg():
    s = FrameSampler(1.0)
    picked = [t / 10 for t in range(35) if s.should_sample(t / 10)]
    assert picked == [0.0, 1.0, 2.0, 3.0]
    jpeg = encode_jpeg(np.zeros((2000, 1000, 3), np.uint8), max_side=1280)
    assert jpeg[:2] == b"\xff\xd8"
