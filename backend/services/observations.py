"""Single entry point for new observations, used by BOTH pipelines:
device uploads (api/observations.py) and server-side video processing (video_processor.py).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Literal

from backend.config import settings
from backend.db.database import connect, utc_now
from backend.services import worker

FRAME_NAME = re.compile(r"^[a-z0-9_-]{1,32}\.jpg$")


def create_observation(
    *,
    source: Literal["device", "upload"],
    timestamp: str,
    obs_type: str,
    frames: list[tuple[str, bytes]],
    device_id: str | None = None,
    job_id: str | None = None,
    video_offset_s: float | None = None,
    metadata: dict | None = None,
) -> str:
    obs_id = uuid.uuid4().hex
    folder = settings.evidence_dir / obs_id
    folder.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for name, data in frames:
        if not FRAME_NAME.match(name):
            raise ValueError(f"invalid frame name {name!r}")
        (folder / name).write_bytes(data)
        names.append(name)

    with connect() as conn:
        conn.execute(
            """INSERT INTO observations
               (id, source, device_id, job_id, timestamp, video_offset_s, type, frames, metadata,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (obs_id, source, device_id, job_id, timestamp, video_offset_s, obs_type,
             json.dumps(names), json.dumps(metadata or {}), utc_now()),
        )
    worker.enqueue(obs_id)
    return obs_id


def load_frames(obs_id: str, names: list[str]) -> list[tuple[str, bytes]]:
    folder = settings.evidence_dir / obs_id
    return [(n, (folder / n).read_bytes()) for n in names if (folder / n).exists()]


def replace_frames(conn, obs_id: str, frames: list[tuple[str, bytes]]) -> None:
    """Make `frames` the evidence of an observation (used when several events are merged)."""
    folder = settings.evidence_dir / obs_id
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in frames:
        (folder / name).write_bytes(data)
    conn.execute("UPDATE observations SET frames = ? WHERE id = ?",
                 (json.dumps([n for n, _ in frames]), obs_id))


def evidence_urls(obs_id: str, names: list[str]) -> list[dict]:
    return [{"name": n.removesuffix(".jpg"), "url": f"/api/v1/evidence/{obs_id}/{n}"} for n in names]
