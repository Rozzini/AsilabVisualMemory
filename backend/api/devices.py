from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.db.database import connect, utc_now
from backend.models.schemas import DeviceRegister, Heartbeat

router = APIRouter(prefix="/devices", tags=["devices"])

DEVICE_SELECT = """
SELECT d.*,
  (SELECT COUNT(*) FROM memories m WHERE m.device_id = d.id) AS memory_count,
  (SELECT COUNT(*) FROM observations o WHERE o.device_id = d.id) AS observation_count,
  (SELECT COUNT(*) FROM observations o WHERE o.device_id = d.id AND o.status = 'pending') AS pending_count,
  (SELECT COUNT(*) FROM observations o WHERE o.device_id = d.id AND o.status = 'dismissed') AS dismissed_count,
  (SELECT COUNT(*) FROM observations o WHERE o.device_id = d.id AND o.status = 'failed') AS failed_count,
  (SELECT COUNT(*) FROM observations o WHERE o.device_id = d.id AND o.status = 'merged') AS merged_count,
  (SELECT MAX(m.timestamp) FROM memories m WHERE m.device_id = d.id) AS last_memory_at
FROM devices d
"""


def _to_dict(row) -> dict:
    d = dict(row)
    d["stats"] = json.loads(d["stats"]) if d.get("stats") else None
    online = False
    if d["last_seen"]:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(d["last_seen"])).total_seconds()
        online = age < settings.device_online_seconds
    d["status"] = "online" if online else "offline"
    return d


def touch_device(conn, device_id: str, name: str | None = None) -> None:
    now = utc_now()
    conn.execute(
        """INSERT INTO devices (id, name, created_at, last_seen) VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET last_seen = excluded.last_seen,
             name = CASE WHEN ? IS NULL THEN devices.name ELSE excluded.name END""",
        (device_id, name or device_id, now, now, name),
    )


@router.post("")
def register_device(body: DeviceRegister):
    with connect() as conn:
        touch_device(conn, body.id, body.name)
    return {"id": body.id}


@router.post("/{device_id}/heartbeat")
def heartbeat(device_id: str, body: Heartbeat):
    with connect() as conn:
        touch_device(conn, device_id)
        conn.execute("UPDATE devices SET stats = ? WHERE id = ?", (json.dumps(body.stats), device_id))
    return {"ok": True}


@router.get("")
def list_devices():
    with connect() as conn:
        rows = conn.execute(DEVICE_SELECT + " ORDER BY d.last_seen DESC").fetchall()
    return [_to_dict(r) for r in rows]


@router.get("/{device_id}")
def get_device(device_id: str):
    with connect() as conn:
        row = conn.execute(DEVICE_SELECT + " WHERE d.id = ?", (device_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Device not found")
    return _to_dict(row)
