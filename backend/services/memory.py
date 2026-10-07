from __future__ import annotations

import json
import sqlite3
import uuid

from backend.db.database import utc_now
from backend.services.observations import evidence_urls
from backend.services.vision import VisionResult

MEMORY_SELECT = """
SELECT m.*, o.frames AS obs_frames, o.type AS obs_type, j.filename AS job_filename, d.name AS device_name
FROM memories m
JOIN observations o ON o.id = m.observation_id
LEFT JOIN jobs j ON j.id = m.job_id
LEFT JOIN devices d ON d.id = m.device_id
"""


def _primary(result: VisionResult):
    for obj in result.objects:
        if obj.action in ("moved", "added", "removed"):
            return obj
    return result.objects[0] if result.objects else None


def create_memory(conn: sqlite3.Connection, obs: sqlite3.Row, result: VisionResult) -> str:
    mem_id = uuid.uuid4().hex
    primary = _primary(result)
    objects = [o.model_dump() for o in result.objects]
    conn.execute(
        """INSERT INTO memories
           (id, observation_id, source, device_id, job_id, timestamp, video_offset_s, event_type,
            summary, objects, location_before, location_after, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (mem_id, obs["id"], obs["source"], obs["device_id"], obs["job_id"], obs["timestamp"],
         obs["video_offset_s"], result.event_type, result.summary, json.dumps(objects),
         primary.location_before if primary else None,
         primary.location_after if primary else None,
         result.confidence, utc_now()),
    )
    object_text = "; ".join(f"{o.name} {o.action}" for o in result.objects)
    locations = "; ".join(
        loc for o in result.objects for loc in (o.location_before, o.location_after) if loc
    )
    conn.execute(
        "INSERT INTO memories_fts (memory_id, summary, objects, locations) VALUES (?, ?, ?, ?)",
        (mem_id, result.summary, object_text, locations),
    )
    return mem_id


def memory_to_dict(row: sqlite3.Row) -> dict:
    frames = json.loads(row["obs_frames"])
    return {
        "id": row["id"],
        "observation_id": row["observation_id"],
        "source": row["source"],
        "device_id": row["device_id"],
        "device_name": row["device_name"],
        "job_id": row["job_id"],
        "job_filename": row["job_filename"],
        "timestamp": row["timestamp"],
        "video_offset_s": row["video_offset_s"],
        "event_type": row["event_type"],
        "summary": row["summary"],
        "objects": json.loads(row["objects"]),
        "location_before": row["location_before"],
        "location_after": row["location_after"],
        "confidence": row["confidence"],
        "evidence": evidence_urls(row["observation_id"], frames),
    }
