from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.config import settings
from backend.db.database import connect, utc_now
from backend.services import video_processor
from backend.services.jobs import JOB_SELECT, job_to_dict

router = APIRouter(prefix="/jobs", tags=["uploads"])

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


@router.post("", status_code=201)
def upload_video(file: UploadFile = File(...)):
    """Portal upload: the server processes the video itself (no device involved)."""
    filename = Path(file.filename or "video.mp4").name
    ext = Path(filename).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(422, f"Unsupported video type {ext!r}")

    job_id = uuid.uuid4().hex
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.uploads_dir / f"{job_id}{ext}"
    limit = settings.max_upload_mb * 1024 * 1024
    written = 0
    with dest.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Video larger than {settings.max_upload_mb} MB")
            out.write(chunk)

    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, filename, video_path, status, created_at) VALUES (?, ?, ?, 'queued', ?)",
            (job_id, filename, str(dest), utc_now()),
        )
        row = conn.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    video_processor.enqueue(job_id)
    return job_to_dict(row)


@router.get("")
def list_jobs():
    with connect() as conn:
        rows = conn.execute(JOB_SELECT + " ORDER BY j.created_at DESC").fetchall()
    return [job_to_dict(r) for r in rows]


@router.get("/{job_id}")
def get_job(job_id: str):
    with connect() as conn:
        row = conn.execute(JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Upload not found")
    return job_to_dict(row)
