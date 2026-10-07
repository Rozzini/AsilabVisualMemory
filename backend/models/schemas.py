from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceRegister(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    name: str = Field(max_length=128)


class Heartbeat(BaseModel):
    stats: dict = Field(default_factory=dict)


class ObservationMetadata(BaseModel):
    """`metadata` form field of POST /observations (device protocol)."""

    device_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    timestamp: datetime
    observation_type: Literal["baseline", "visual_change", "activity"]
    event_start: datetime | None = None
    event_end: datetime | None = None
    scores: dict = Field(default_factory=dict)
    forced: bool = False


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    device_id: str | None = None
    job_id: str | None = None
