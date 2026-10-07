"""Server-side pipeline for videos uploaded through the portal.

Independent of the device agent: the server decodes the file itself, samples it, runs the
same change detector and creates observations directly (source="upload").
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime, timedelta

import cv2

from backend.db.database import connect, to_iso, utc_now
from backend.services.jobs import maybe_complete, update_job
from backend.services.observations import create_observation
from detection import ChangeDetector, RollingBuffer, encode_jpeg, evidence_frames

log = logging.getLogger(__name__)

SAMPLE_INTERVAL_S = 1.0

_queue: "queue.Queue[str]" = queue.Queue()
_thread: threading.Thread | None = None


def enqueue(job_id: str) -> None:
    _queue.put(job_id)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    with connect() as conn:
        # Jobs interrupted by a restart are re-run from the start.
        stale = [r["id"] for r in conn.execute(
            "SELECT id FROM jobs WHERE status IN ('queued', 'processing') ORDER BY created_at")]
        conn.execute(
            "DELETE FROM memories_fts WHERE memory_id IN (SELECT id FROM memories WHERE job_id IN "
            "(SELECT id FROM jobs WHERE status = 'processing'))")
        conn.execute("DELETE FROM memories WHERE job_id IN (SELECT id FROM jobs WHERE status = 'processing')")
        conn.execute("DELETE FROM observations WHERE job_id IN (SELECT id FROM jobs WHERE status = 'processing')")
        conn.execute("UPDATE jobs SET status = 'queued', progress = 0, observations_total = 0 "
                     "WHERE status = 'processing'")
    for job_id in stale:
        enqueue(job_id)
    _thread = threading.Thread(target=_run, daemon=True, name="video-processor")
    _thread.start()


def _run() -> None:
    while True:
        job_id = _queue.get()
        try:
            process(job_id)
        except Exception as exc:
            log.exception("Job %s failed", job_id)
            update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}", completed_at=utc_now())


def process(job_id: str) -> None:
    with connect() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None or job["status"] != "queued":
        return

    cap = cv2.VideoCapture(job["video_path"])
    if not cap.isOpened():
        raise RuntimeError("Could not decode the video file")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    duration = total / fps if total else None
    update_job(job_id, status="processing", duration_s=duration)

    # Memories get a wall-clock timestamp anchored at upload time plus the video offset.
    base = datetime.fromisoformat(job["created_at"])
    detector = ChangeDetector()
    buffer = RollingBuffer(max_seconds=90)
    pos, next_sample, created = 0, 0.0, 0
    last_progress = time.time()

    try:
        while cap.grab():
            offset = pos / fps
            pos += 1
            if offset < next_sample:
                continue
            ok, frame = cap.retrieve()
            if not ok:
                continue
            next_sample = offset + SAMPLE_INTERVAL_S
            buffer.add(offset, encode_jpeg(frame))
            ev = detector.process(offset, frame)
            if ev is not None:
                create_observation(
                    source="upload",
                    job_id=job_id,
                    timestamp=to_iso(base + timedelta(seconds=ev.after_ts)),
                    video_offset_s=round(ev.after_ts, 2),
                    obs_type=ev.type,
                    frames=evidence_frames(ev, buffer),
                    metadata={"scores": ev.scores, "forced": ev.forced,
                              "event_start_s": ev.start_ts, "event_end_s": ev.end_ts},
                )
                created += 1
                update_job(job_id, observations_total=created)
            if time.time() - last_progress > 0.5 and total:
                update_job(job_id, progress=round(min(pos / total, 1.0), 3))
                last_progress = time.time()
    finally:
        cap.release()

    update_job(job_id, status="analyzing", progress=1.0, observations_total=created,
               stats=json.dumps(detector.stats.as_dict()))
    log.info("Job %s: %d observation(s) from %d samples", job_id[:8], created, detector.stats.samples)
    maybe_complete(job_id)
