from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.config import settings
from backend.services.observations import FRAME_NAME

router = APIRouter(tags=["evidence"])

OBS_ID = re.compile(r"^[0-9a-f]{32}$")


@router.get("/evidence/{obs_id}/{filename}")
def get_evidence(obs_id: str, filename: str):
    if not OBS_ID.match(obs_id) or not FRAME_NAME.match(filename):
        raise HTTPException(404, "Not found")
    path = settings.evidence_dir / obs_id / filename
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
