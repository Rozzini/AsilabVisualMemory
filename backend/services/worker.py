"""Analysis worker: one background thread, one observation at a time (one GPU / one model).

observation (pending) → VisionService → memory (processed) | dismissed | failed
                                       └ merged into a later observation when a live device backlogs
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


def _scores(obs) -> dict:
    return json.loads(obs["metadata"] or "{}").get("scores") or {}


def process(obs_id: str) -> None:
    # Imported lazily to avoid import cycles (observations → worker → memory → observations).
    from backend.services.jobs import maybe_complete
    from backend.services.observations import load_frames
    from backend.services.vision import get_vision

    with connect() as conn:
        obs = conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
    if obs is None or obs["status"] != "pending":
        return

    if obs["source"] == "device" and obs["type"] != "baseline":
        run = _pending_run(obs)
        if len(run) >= MERGE_MIN:
            _process_merged(run)
            return

    frames = load_frames(obs_id, json.loads(obs["frames"]))
    previous = _previous_memory(obs)
    result, error, unavailable = _analyze(
        obs_id, lambda: get_vision().analyze(obs["type"], frames, _when(obs), previous, _scores(obs))
    )
    if result is None and unavailable:
        _retry_later(obs_id, error)
        return
    with connect() as conn:
        _store(conn, obs, result, error)
    maybe_complete(obs["job_id"])


def _analyze(label: str, call):
    """Run a model call with retries. Returns (result, error, model_unavailable)."""
    from backend.services.vision import VisionUnavailable

    error, unavailable = None, False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call(), None, False
        except VisionUnavailable as exc:
            unavailable, error = True, str(exc)
            log.warning("Vision unavailable (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)
            time.sleep(2 ** attempt)
        except Exception as exc:  # bad JSON twice, invalid image...
            unavailable, error = False, f"{type(exc).__name__}: {exc}"
            log.warning("Vision failed for %s (attempt %d/%d): %s", label, attempt, MAX_ATTEMPTS, error)
    return None, error, unavailable


def _retry_later(obs_id: str, error: str | None) -> None:
    """Model server down: keep the observation pending and try again later."""
    with connect() as conn:
        conn.execute("UPDATE observations SET attempts = attempts + ?, error = ? WHERE id = ?",
                     (MAX_ATTEMPTS, error, obs_id))
    threading.Timer(RETRY_LATER_S, enqueue, args=(obs_id,)).start()


def _store(conn, obs, result, error) -> None:
    from backend.services.memory import create_memory

    if result is None:
        conn.execute(
            "UPDATE observations SET status = 'failed', attempts = attempts + ?, error = ? WHERE id = ?",
            (MAX_ATTEMPTS, error, obs["id"]),
        )
        log.error("Observation %s failed: %s", obs["id"], error)
        return
    status = "processed" if result.is_meaningful else "dismissed"
    if result.is_meaningful:
        create_memory(conn, obs, result)
    conn.execute(
        "UPDATE observations SET status = ?, attempts = attempts + 1, result = ?, error = NULL WHERE id = ?",
        (status, result.model_dump_json(), obs["id"]),
    )
    log.info("Observation %s %s: %s", obs["id"][:8], status, result.summary)


# --- keeping up with a live device -------------------------------------------------------
# When events from a device arrive faster than the model can analyse them, the queued run
# is merged into one analysis: memories become coarser instead of arriving minutes late.
# Uploaded videos are never merged (not live; completeness matters more there).

MERGE_MIN = 3  # merge when this observation has at least 2 newer pending ones behind it
MERGE_MAX = 6


def _pending_run(obs) -> list:
    """This observation plus the consecutive pending events of the same device after it."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM observations WHERE device_id = ? AND source = 'device' AND status = 'pending' "
            "AND timestamp >= ? AND id != ? ORDER BY timestamp LIMIT ?",
            (obs["device_id"], obs["timestamp"], obs["id"], MERGE_MAX - 1),
        ).fetchall()
    run = [obs]
    for row in rows:
        if row["type"] == "baseline":  # a restarted device: its new baseline stays separate
            break
        run.append(row)
    return run


def _process_merged(run: list) -> None:
    from backend.services.observations import load_frames, replace_frames
    from backend.services.vision import get_vision

    first, last = run[0], run[-1]
    busiest = max(run, key=lambda o: _scores(o).get("peak_motion", 0))

    def frame(obs, names: list[str]):
        for name in names:
            got = load_frames(obs["id"], [name])
            if got:
                return got[0][1]
        return None

    picks = [("before.jpg", frame(first, ["before.jpg", "after.jpg"])),
             ("mid.jpg", frame(busiest, ["mid.jpg", "after.jpg"])),
             ("after.jpg", frame(last, ["after.jpg"]))]
    frames = [(name, data) for name, data in picks if data is not None]

    first_s, last_s = _scores(first), _scores(last)
    camera = max(run, key=lambda o: _scores(o).get("view_shift_explains", 0))
    scores = {
        "brightness_before": first_s.get("brightness_before"),
        "brightness_after": last_s.get("brightness_after"),
        "view_shift": _scores(camera).get("view_shift", 0),
        "view_shift_explains": _scores(camera).get("view_shift_explains", 0),
    }
    span = f"between {_when(first)} and {_when(last)}"
    note = (f"These frames summarise {len(run)} consecutive events {span} (the camera was busy). "
            "Describe everything that happened over that whole period in one or two sentences.")
    log.info("Analysis backlog for %s: merging %d events %s", first["device_id"], len(run), span)

    previous = _previous_memory(first)
    result, error, unavailable = _analyze(
        last["id"], lambda: get_vision().analyze("activity", frames, span, previous, scores, note)
    )
    if result is None and unavailable:
        _retry_later(first["id"], error)  # the run is rebuilt when it is retried
        return

    others = [o["id"] for o in run[:-1]]
    with connect() as conn:
        replace_frames(conn, last["id"], frames)
        _store(conn, last, result, error)
        conn.execute(
            f"UPDATE observations SET status = 'merged', result = ? "
            f"WHERE id IN ({','.join('?' * len(others))})",
            (json.dumps({"merged_into": last["id"]}), *others),
        )
