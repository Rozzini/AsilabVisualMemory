"""Analysis worker: one background thread, one observation at a time (one GPU / one model).

observation (pending) → VisionService → memory (processed) | dismissed | failed
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime

from backend.db.database import connect

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_LATER_S = 30.0

_queue: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None


def enqueue(obs_id: str) -> None:
    _queue.put(obs_id)


def requeue_pending() -> None:
    """Queue every pending observation (duplicates are harmless: process() skips non-pending)."""
    with connect() as conn:
        pending = [r["id"] for r in conn.execute(
            "SELECT id FROM observations WHERE status = 'pending' ORDER BY timestamp")]
    for obs_id in pending:
        enqueue(obs_id)
    if pending:
        log.info("Re-enqueued %d pending observation(s)", len(pending))


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    requeue_pending()
    _thread = threading.Thread(target=_run, daemon=True, name="analysis-worker")
    _thread.start()


def queue_size() -> int:
    return _queue.qsize()


def _run() -> None:
    while True:
        obs_id = _queue.get()
        try:
            process(obs_id)
        except Exception:
            log.exception("Unexpected error processing observation %s", obs_id)


def _when(obs) -> str:
    if obs["video_offset_s"] is not None:
        m, s = divmod(int(obs["video_offset_s"]), 60)
        return f"{m:02d}:{s:02d} into the uploaded video"
    try:
        return datetime.fromisoformat(obs["timestamp"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return obs["timestamp"]


def _previous_memory(obs) -> str | None:
    """Latest memory from the same device / upload before this observation (context for the model)."""
    with connect() as conn:
        if obs["job_id"]:
            row = conn.execute(
                "SELECT summary, video_offset_s, timestamp FROM memories WHERE job_id = ? "
                "AND video_offset_s < ? ORDER BY video_offset_s DESC LIMIT 1",
                (obs["job_id"], obs["video_offset_s"] or 0),
            ).fetchone()
        elif obs["device_id"]:
            row = conn.execute(
                "SELECT summary, video_offset_s, timestamp FROM memories WHERE device_id = ? "
                "AND timestamp < ? ORDER BY timestamp DESC LIMIT 1",
                (obs["device_id"], obs["timestamp"]),
            ).fetchone()
        else:
            row = None
    return f"({_when(row)}) {row['summary']}" if row else None


def process(obs_id: str) -> None:
    # Imported lazily to avoid import cycles (observations → worker → memory → observations).
    from backend.services.jobs import maybe_complete
    from backend.services.memory import create_memory
    from backend.services.observations import load_frames
    from backend.services.vision import VisionUnavailable, get_vision

    with connect() as conn:
        obs = conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
    if obs is None or obs["status"] != "pending":
        return

    frames = load_frames(obs_id, json.loads(obs["frames"]))
    previous = _previous_memory(obs)
    result, error, unavailable = None, None, False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            scores = json.loads(obs["metadata"] or "{}").get("scores")
            result = get_vision().analyze(obs["type"], frames, _when(obs), previous, scores)
            break
        except VisionUnavailable as exc:
            unavailable, error = True, str(exc)
            log.warning("Vision unavailable (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)
            time.sleep(2 ** attempt)
        except Exception as exc:  # bad JSON twice, invalid image...
            unavailable, error = False, f"{type(exc).__name__}: {exc}"
            log.warning("Vision failed for %s (attempt %d/%d): %s", obs_id, attempt, MAX_ATTEMPTS, error)

    if result is None and unavailable:
        # Model server down: keep the observation pending and try again later.
        with connect() as conn:
            conn.execute(
                "UPDATE observations SET attempts = attempts + ?, error = ? WHERE id = ?",
                (MAX_ATTEMPTS, error, obs_id),
            )
        threading.Timer(RETRY_LATER_S, enqueue, args=(obs_id,)).start()
        return

    with connect() as conn:
        if result is None:
            conn.execute(
                "UPDATE observations SET status = 'failed', attempts = attempts + ?, error = ? WHERE id = ?",
                (MAX_ATTEMPTS, error, obs_id),
            )
            log.error("Observation %s failed: %s", obs_id, error)
        else:
            status = "processed" if result.is_meaningful else "dismissed"
            if result.is_meaningful:
                create_memory(conn, obs, result)
            conn.execute(
                "UPDATE observations SET status = ?, attempts = attempts + 1, result = ?, error = NULL WHERE id = ?",
                (status, result.model_dump_json(), obs_id),
            )
            log.info("Observation %s %s: %s", obs_id[:8], status, result.summary)
    maybe_complete(obs["job_id"])
