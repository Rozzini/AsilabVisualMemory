from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.db.database import connect
from backend.services import worker
from backend.services.memory import MEMORY_SELECT, memory_to_dict

router = APIRouter(tags=["memories"])


@router.get("/memories")
def list_memories(
    device_id: str | None = None,
    job_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    before: str | None = Query(None, description="cursor: return memories older than this timestamp"),
):
    """Memory history for one device, one uploaded video, or everything."""
    where, params = ["1=1"], []
    if device_id:
        where.append("m.device_id = ?")
        params.append(device_id)
    if job_id:
        where.append("m.job_id = ?")
        params.append(job_id)
        order = "m.video_offset_s ASC"  # an upload reads like a story, start to end
    else:
        order = "m.timestamp DESC"
        if before:
            where.append("m.timestamp < ?")
            params.append(before)
    sql = MEMORY_SELECT + " WHERE " + " AND ".join(where) + f" ORDER BY {order} LIMIT ?"
    with connect() as conn:
        rows = conn.execute(sql, [*params, limit]).fetchall()
    return [memory_to_dict(r) for r in rows]


@router.get("/memories/{memory_id}")
def get_memory(memory_id: str):
    with connect() as conn:
        row = conn.execute(MEMORY_SELECT + " WHERE m.id = ?", (memory_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Memory not found")
    return memory_to_dict(row)


@router.get("/stats")
def stats():
    """How much the pipeline filters: candidates sent vs memories kept."""
    with connect() as conn:
        obs = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM observations GROUP BY status")}
        memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    return {"observations": obs, "memories": memories, "analysis_queue": worker.queue_size()}
