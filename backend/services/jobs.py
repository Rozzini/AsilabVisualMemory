from __future__ import annotations

import json
import sqlite3

from backend.db.database import connect, utc_now

JOB_SELECT = """
SELECT j.*,
  (SELECT COUNT(*) FROM observations o WHERE o.job_id = j.id AND o.status != 'pending') AS observations_done,
  (SELECT COUNT(*) FROM memories m WHERE m.job_id = j.id) AS memory_count,
  (SELECT COUNT(*) FROM observations o WHERE o.job_id = j.id AND o.status = 'dismissed') AS dismissed_count
FROM jobs j
"""


def job_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("video_path", None)
    d["stats"] = json.loads(d["stats"]) if d.get("stats") else None
    return d


def update_job(job_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def maybe_complete(job_id: str | None) -> None:
    """An upload is complete once the video is processed and every observation is analysed."""
    if not job_id:
        return
    with connect() as conn:
        conn.execute(
            """UPDATE jobs SET status = 'completed', completed_at = ?
               WHERE id = ? AND status = 'analyzing'
                 AND NOT EXISTS (SELECT 1 FROM observations WHERE job_id = ? AND status = 'pending')""",
            (utc_now(), job_id, job_id),
        )
