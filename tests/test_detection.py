import numpy as np

from detection import ChangeDetector, FrameSampler, RollingBuffer, encode_jpeg

RNG = np.random.default_rng(0)


def scene(objects=(), noise=3, brightness=0):
    """640x480 gray room with optional filled rectangles (x, y, w, h, value)."""
    img = np.full((480, 640, 3), 120, np.uint8)
    img[300:, :] = 90  # "desk"
    for x, y, w, h, v in objects:
        img[y : y + h, x : x + w] = v
    jitter = RNG.integers(-noise, noise + 1, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + jitter + brightness, 0, 255).astype(np.uint8)


KEYS_ON_DESK = (100, 320, 60, 30, 230)
KEYS_ON_SHELF = (450, 120, 60, 30, 230)
PERSON = (200, 50, 200, 430, 30)


def seated(dx=0, dy=0):
    """A person sitting in view, shifted by a few pixels (breathing, small movements)."""
    return (220 + dx, 150 + dy, 160, 330, 40)


def run(frames, cfg=None):  # cfg: optional DetectorConfig
    det = ChangeDetector(cfg)
    events = [e for t, f in enumerate(frames) if (e := det.process(float(t), f))]
    return det, events


def types(events):
    return [e.type for e in events]


def test_first_frame_is_baseline():
    _, events = run([scene()])
    assert types(events) == ["baseline"]


def test_static_scene_emits_nothing_after_baseline():
    det, events = run([scene() for _ in range(30)])
    assert types(events) == ["baseline"]
    assert det.stats.triggers == 0


def test_seated_person_micro_movement_is_not_an_event():
    frames = [scene([seated(*RNG.integers(-3, 4, 2))]) for _ in range(60)]
    det, events = run(frames)
    assert types(events) == ["baseline"]


def test_object_moved_emits_change_shortly_after_motion_stops():
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
    assert ev.after_ts <= 7.0 + 2 + 1  # within settle_samples (+1) after motion stopped


def test_walk_through_is_reported_as_activity():
    frames = (
        [scene([KEYS_ON_DESK])] * 5
        + [scene([KEYS_ON_DESK, PERSON])] * 2
        + [scene([KEYS_ON_DESK]) for _ in range(6)]
    )
    det, events = run(frames)
    assert types(events) == ["baseline", "activity"]
    ev = events[1]
    assert ev.peak_ts in (5.0, 6.0, 7.0) and not ev.forced  # mid frame shows the person


def test_continuous_activity_checkpoints_back_off():
    frames = [scene()] + [
        scene([(i * 20 % 500, 100, 120, 300, 30 + (i % 2) * 150)]) for i in range(1, 76)
    ]
    _, events = run(frames)
    forced = [e for e in events if e.forced]
    assert all(e.type == "activity" for e in forced)
    # after 10 s, then 20 s, then 40 s: 3 checkpoints in 75 s instead of 7
    assert [round(e.end_ts - e.start_ts) for e in forced] == [10, 20, 40]


def test_small_motionless_drift_is_dropped():
    # auto-exposure style: one region slowly brightens by 2 levels per second, nothing moves
    frames = [scene([(300, 60, 120, 90, 120 + 2 * t)], noise=0) for t in range(40)]
    det, events = run(frames)
    assert types(events) == ["baseline"]
    assert det.stats.discarded >= 1


def test_large_slow_change_is_still_reported():
    # dusk: the whole room slowly darkens, nothing moves
    frames = [scene(noise=0, brightness=-2 * t) for t in range(40)]
    _, events = run(frames)
    assert "visual_change" in types(events)


def test_light_switched_off_is_a_change_with_brightness_measured():
    frames = [scene()] * 5 + [scene(brightness=-70) for _ in range(5)]
    _, events = run(frames)
    assert types(events) == ["baseline", "visual_change"]
    s = events[1].scores
    assert s["brightness_after"] < 0.6 * s["brightness_before"]
    assert s["view_shift_explains"] < 0.6  # no "camera moved" hint for a lighting change


def test_camera_turned_is_measured_as_view_shift():
    base = scene([KEYS_ON_DESK, KEYS_ON_SHELF])
    turned = np.full_like(base, 100)
    turned[:, :460] = base[:, 180:]  # view panned by 180 px
    _, events = run([base] * 5 + [turned] * 5)
    s = events[1].scores
    assert s["view_shift"] > 0.2 and s["view_shift_explains"] > 0.6


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
