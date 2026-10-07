from __future__ import annotations

import json

import httpx


class ApiClient:
    """Device side of the observation protocol. Knows nothing about vision models."""

    def __init__(self, base_url: str, device_id: str, timeout: float = 15.0):
        self.device_id = device_id
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", timeout=timeout)

    def register(self, name: str) -> None:
        self.http.post("/devices", json={"id": self.device_id, "name": name}).raise_for_status()

    def heartbeat(self, stats: dict) -> None:
        self.http.post(f"/devices/{self.device_id}/heartbeat", json={"stats": stats}).raise_for_status()

    def post_observation(self, metadata: dict, frames: list[tuple[str, bytes]]) -> dict:
        files = [("frames", (name, data, "image/jpeg")) for name, data in frames]
        resp = self.http.post(
            "/observations", data={"metadata": json.dumps(metadata)}, files=files
        )
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self.http.close()
