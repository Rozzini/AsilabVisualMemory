"""Generate a small synthetic demo video (no webcam needed).

Scene: a desk and a shelf. Keys lie on the desk, a person reaches in and moves them to the
shelf, then later someone walks through without changing anything (should be ignored).

    uv run python scripts/make_demo_video.py [demo.mp4]
"""

import sys

import cv2
import numpy as np

FPS = 15
W, H = 640, 480
DESK, SHELF = (100, 340), (480, 70)
rng = np.random.default_rng(1)


def frame(keys_at: tuple[int, int], person: bool) -> np.ndarray:
    img = np.full((H, W, 3), (150, 140, 130), np.uint8)
    cv2.rectangle(img, (0, 320), (W, H), (60, 90, 120), -1)
    cv2.putText(img, "DESK", (20, 460), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (230, 230, 230), 3)
    cv2.rectangle(img, (400, 100), (620, 120), (40, 60, 80), -1)
    cv2.putText(img, "SHELF", (450, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 40, 40), 2)
    x, y = keys_at
    cv2.circle(img, (x + 12, y + 12), 11, (0, 200, 255), 4)
    cv2.rectangle(img, (x + 22, y + 9), (x + 70, y + 15), (0, 200, 255), -1)
    cv2.rectangle(img, (x + 58, y + 15), (x + 63, y + 24), (0, 200, 255), -1)
    cv2.putText(img, "KEYS", (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2)
    if person:  # simple silhouette: head, torso, arms, legs
        dark = (40, 35, 30)
        cv2.circle(img, (335, 85), 38, dark, -1)
        cv2.rectangle(img, (285, 130), (385, 330), dark, -1)
        cv2.line(img, (285, 150), (235, 300), dark, 22)
        cv2.line(img, (385, 150), (440, 290), dark, 22)
        cv2.line(img, (305, 330), (295, 480), dark, 30)
        cv2.line(img, (365, 330), (375, 480), dark, 30)
    noise = rng.integers(-3, 4, img.shape, dtype=np.int16)  # sensor noise
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def main() -> None:
    out_path = sys.argv[1] if len(sys.argv) > 1 else "demo.mp4"
    fourcc = cv2.VideoWriter_fourcc(*("mp4v" if out_path.endswith(".mp4") else "MJPG"))
    out = cv2.VideoWriter(out_path, fourcc, FPS, (W, H))
    if not out.isOpened():
        raise SystemExit(f"Cannot write {out_path}")
    seq = (
        [(DESK, False)] * 6 * FPS      # quiet scene, keys on the desk
        + [(DESK, True)] * 2 * FPS     # person reaches in
        + [(SHELF, True)] * 1 * FPS    # ...and moves the keys
        + [(SHELF, False)] * 6 * FPS   # keys now on the shelf
        + [(SHELF, True)] * 2 * FPS    # someone walks through
        + [(SHELF, False)] * 6 * FPS   # nothing changed
    )
    for keys, person in seq:
        out.write(frame(keys, person))
    out.release()
    print(f"Wrote {out_path} ({len(seq) / FPS:.0f} s)")


if __name__ == "__main__":
    main()
