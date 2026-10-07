from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from backend.api.devices import touch_device
from backend.db.database import connect, to_iso
from backend.models.schemas import ObservationMetadata
from backend.services import worker
from backend.services.observations import FRAME_NAME, create_observation, evidence_urls

router = APIRouter(prefix="/observations", tags=["observations"])

MAX_FRAMES = 5
MAX_FRAME_BYTES = 5 * 1024 * 1024


@router.post("", status_code=202)
async def ingest_observation(metadata: str = Form(...), frames: list[UploadFile] = File(...)):
    """Device protocol: 'potentially meaningful visual evidence occurred here'."""
    try:
        meta = ObservationMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False)) from exc
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise HTTPException(422, f"expected 1-{MAX_FRAMES} frames")

    data: list[tuple[str, bytes]] = []
    for f in frames:
        name = (f.filename or "").lower()
        if not FRAME_NAME.match(name):
            raise HTTPException(422, f"invalid frame name {f.filename!r}")
        content = await f.read()
        if len(content) > MAX_FRAME_BYTES or content[:2] != b"\xff\xd8":
            raise HTTPException(422, f"{name} must be a JPEG under {MAX_FRAME_BYTES // 1024 // 1024} MB")
        data.append((name, content))

    with connect() as conn:
        touch_device(conn, meta.device_id)
    obs_id = create_observation(
        source="device",
        device_id=meta.device_id,
        timestamp=to_iso(meta.timestamp),
        obs_type=meta.observation_type,
        frames=data,
        metadata=meta.model_dump(mode="json", exclude={"device_id", "timestamp", "observation_type"}),
    )
    return {"id": obs_id, "status": "pending"}


@router.get("/{obs_id}")
def get_observation(obs_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Observation not found")
    d = dict(row)
    frames = json.loads(d.pop("frames"))
    d["metadata"] = json.loads(d["metadata"] or "{}")
    d["result"] = json.loads(d["result"]) if d["result"] else None
    d["evidence"] = evidence_urls(obs_id, frames)
    return d


@router.post("/retry-failed")
def retry_failed():
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM observations WHERE status = 'failed'")]
        # re-open uploads that completed with failures so they complete again afterwards
        conn.execute(
            """UPDATE jobs SET status = 'analyzing', completed_at = NULL
               WHERE status = 'completed'
                 AND id IN (SELECT job_id FROM observations WHERE status = 'failed')"""
        )
        conn.execute("UPDATE observations SET status = 'pending' WHERE status = 'failed'")
    for obs_id in ids:
        worker.enqueue(obs_id)
    return {"requeued": len(ids)}
