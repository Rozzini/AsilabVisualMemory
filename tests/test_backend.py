import json
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.services import retrieval, vision
from backend.services.vision import Answer, VisionResult, extract_json


def jpeg(color=(120, 120, 120)) -> bytes:
    img = np.full((240, 320, 3), color, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


class FakeVision:
    def analyze(self, obs_type, frames, when):
        if obs_type == "baseline":
            return VisionResult(is_meaningful=True, event_type="baseline",
                                summary="A desk with a phone and keys.",
                                objects=[{"name": "keys", "action": "present", "location_after": "on the desk"}],
                                confidence=0.8)
        return VisionResult(is_meaningful=True, event_type="object_moved",
                            summary="Keys were moved from the desk to the shelf.",
                            objects=[{"name": "keys", "action": "moved",
                                      "location_before": "on the desk", "location_after": "on the shelf"}],
                            confidence=0.9)

    def answer(self, question, lines):
        mem_id = lines[-1].split("]")[0].strip("[")
        return Answer(answer="Your keys were last seen on the shelf.", memory_ids=[mem_id])


@pytest.fixture(scope="module")
def client():
    vision._service = FakeVision()
    from backend.main import app

    with TestClient(app) as c:
        yield c


def wait_for(fn, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return
        time.sleep(0.1)
    raise AssertionError("timed out")


def post_obs(client, obs_type, ts, names=("after.jpg",)):
    meta = {"device_id": "cam-1", "timestamp": ts, "observation_type": obs_type}
    files = [("frames", (n, jpeg(), "image/jpeg")) for n in names]
    r = client.post("/api/v1/observations", data={"metadata": json.dumps(meta)}, files=files)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_extract_json_handles_think_and_fences():
    text = '<think>hmm {"no": 1}</think>Sure!\n```json\n{"is_meaningful": false, "summary": "x"}\n```'
    assert extract_json(text) == {"is_meaningful": False, "summary": "x"}


def test_vision_result_normalises_sloppy_output():
    r = VisionResult.model_validate({
        "is_meaningful": True, "event_type": "Object Moved", "summary": "s", "confidence": "1.7",
        "objects": [{"name": "mug", "action": "MOVED", "location_before": "null", "location_after": "sink"}],
    })
    assert r.event_type == "object_moved" and r.confidence == 1.0
    assert r.objects[0].action == "moved" and r.objects[0].location_before is None


def test_fts_query_drops_question_words():
    assert retrieval.build_fts_query("Where did I leave my keys?") == "keys"
    assert retrieval.build_fts_query("where is it?") is None


def test_device_observation_to_memory_to_answer(client):
    client.post("/api/v1/devices", json={"id": "cam-1", "name": "Desk cam"})
    post_obs(client, "baseline", "2026-10-07T12:00:00Z")
    obs_id = post_obs(client, "visual_change", "2026-10-07T12:30:00Z", ("before.jpg", "after.jpg"))

    wait_for(lambda: client.get(f"/api/v1/observations/{obs_id}").json()["status"] == "processed")

    mems = client.get("/api/v1/memories", params={"device_id": "cam-1"}).json()
    assert [m["event_type"] for m in mems] == ["object_moved", "baseline"]  # newest first
    assert mems[0]["evidence"][0]["url"].startswith(f"/api/v1/evidence/{obs_id}/")
    assert client.get(mems[0]["evidence"][0]["url"]).status_code == 200

    devices = client.get("/api/v1/devices").json()
    assert devices[0]["status"] == "online" and devices[0]["memory_count"] == 2

    ans = client.post("/api/v1/query", json={"query": "Where did I leave my keys?", "device_id": "cam-1"}).json()
    assert ans["used_llm"] and "shelf" in ans["answer"]
    assert ans["memories"][0]["event_type"] == "object_moved"


def test_upload_pipeline_is_independent_of_devices(client, tmp_path):
    # 6 s synthetic video: empty desk, then a bright "object" appears and stays.
    path = tmp_path / "demo.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    for i in range(80):
        frame = np.full((240, 320, 3), 100, np.uint8)
        if i >= 30:
            frame[100:160, 100:180] = 240
        out.write(frame)
    out.release()

    with path.open("rb") as f:
        job = client.post("/api/v1/jobs", files={"file": ("demo.avi", f, "video/x-msvideo")}).json()
    wait_for(lambda: client.get(f"/api/v1/jobs/{job['id']}").json()["status"] == "completed")

    job = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert job["observations_total"] == 2 and job["memory_count"] == 2
    mems = client.get("/api/v1/memories", params={"job_id": job["id"]}).json()
    assert all(m["source"] == "upload" and m["device_id"] is None for m in mems)
    assert mems[0]["video_offset_s"] < mems[1]["video_offset_s"]  # video order

    # scoped query does not see device memories
    ans = client.post("/api/v1/query", json={"query": "keys", "job_id": job["id"]}).json()
    assert all(m["job_id"] == job["id"] for m in ans["memories"])


def test_rejects_bad_observations(client):
    meta = {"device_id": "cam-1", "timestamp": "2026-10-07T12:00:00Z", "observation_type": "visual_change"}
    r = client.post("/api/v1/observations", data={"metadata": json.dumps(meta)},
                    files=[("frames", ("../evil.jpg", jpeg(), "image/jpeg"))])
    assert r.status_code == 422
    r = client.post("/api/v1/observations", data={"metadata": json.dumps(meta)},
                    files=[("frames", ("after.jpg", b"not a jpeg", "image/jpeg"))])
    assert r.status_code == 422
