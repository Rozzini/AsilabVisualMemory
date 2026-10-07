import json
import threading
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
    def __init__(self):
        self.calls = []
        self.gate = threading.Event()  # cleared = the "model" is busy
        self.gate.set()

    def analyze(self, obs_type, frames, when, previous=None, scores=None, note=None):
        self.calls.append({"type": obs_type, "previous": previous, "scores": scores, "note": note,
                           "frames": [n for n, _ in frames]})
        self.gate.wait(10)
        if note:  # several queued events merged into one analysis
            return VisionResult(is_meaningful=True, event_type="person_activity",
                                summary="A person moved around the desk for a while.")
        if obs_type == "activity":
            return VisionResult(is_meaningful=False, summary="Nothing new happened.")
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


def post_obs(client, obs_type, ts, names=("after.jpg",), device="cam-1", peak=0.1):
    meta = {"device_id": device, "timestamp": ts, "observation_type": obs_type,
            "scores": {"peak_motion": peak}}
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


def test_measurement_hints_for_lighting_and_camera_moves():
    from backend.services.vision import measurement_hints

    assert "darker" in measurement_hints({"brightness_before": 0.5, "brightness_after": 0.15})
    assert "brighter" in measurement_hints({"brightness_before": 0.15, "brightness_after": 0.5})
    moved = measurement_hints({"brightness_before": 0.5, "brightness_after": 0.5,
                               "view_shift": 0.34, "view_shift_explains": 0.9})
    assert "camera itself was probably moved" in moved
    assert measurement_hints({"brightness_before": 0.5, "brightness_after": 0.48, "view_shift": 0.0}) == ""
    assert measurement_hints(None) == ""


def test_measured_facts_override_a_dismissive_model(monkeypatch):
    from backend.services.vision import VisionService

    svc = VisionService()
    calls = []

    def fake_describe(obs_type, frames, when, previous=None, scores=None, note=None):
        calls.append(obs_type)
        if obs_type == "baseline":
            return VisionResult(is_meaningful=True, summary="A wall with a poster.",
                                objects=[{"name": "poster", "action": "present", "location_after": "on the wall"}])
        return VisionResult(is_meaningful=False, summary="No change in the scene.")

    monkeypatch.setattr(svc, "_describe", fake_describe)
    frames = [("before.jpg", b""), ("after.jpg", b"")]

    dark = svc.analyze("visual_change", frames, "now",
                       scores={"brightness_before": 0.48, "brightness_after": 0.14, "view_shift": 0.0})
    assert dark.is_meaningful and dark.event_type == "lighting_change" and "switched off" in dark.summary

    moved = svc.analyze("visual_change", frames, "now", scores={
        "brightness_before": 0.48, "brightness_after": 0.47, "view_shift": 0.34, "view_shift_explains": 1.0})
    assert moved.event_type == "camera_moved" and "poster" in moved.summary
    assert moved.objects[0].name == "poster" and calls[-1] == "baseline"  # inventory of the new view

    nothing = svc.analyze("visual_change", frames, "now",
                          scores={"brightness_before": 0.48, "brightness_after": 0.47, "view_shift": 0.0})
    assert not nothing.is_meaningful


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

    # the model got the previous memory of this device as context
    change_call = [c for c in vision._service.calls if c["type"] == "visual_change"][0]
    assert "A desk with a phone and keys." in change_call["previous"]


def test_dismissed_events_are_listed_with_reason(client):
    obs_id = post_obs(client, "activity", "2026-10-07T12:40:00Z", ("before.jpg", "mid.jpg", "after.jpg"))
    wait_for(lambda: client.get(f"/api/v1/observations/{obs_id}").json()["status"] == "dismissed")

    ignored = client.get("/api/v1/observations", params={"device_id": "cam-1", "status": "dismissed"}).json()
    assert ignored[0]["id"] == obs_id
    assert ignored[0]["result"]["summary"] == "Nothing new happened."
    assert len(ignored[0]["evidence"]) == 3
    device = client.get("/api/v1/devices/cam-1").json()
    assert device["dismissed_count"] == 1 and device["pending_count"] == 0


def test_device_backlog_is_merged_into_one_analysis(client):
    fake = vision._service
    frames3 = ("before.jpg", "mid.jpg", "after.jpg")
    fake.gate.clear()  # the model is busy with the first event...
    first = post_obs(client, "visual_change", "2026-10-07T13:00:00Z", frames3, device="cam-busy")
    wait_for(lambda: any(c["type"] == "visual_change" and c["note"] is None for c in fake.calls[-1:]))
    # ...while four more events queue up
    queued = [post_obs(client, "activity", f"2026-10-07T13:00:{10 * i}Z", frames3, device="cam-busy",
                       peak=0.1 * i) for i in range(1, 5)]
    calls_before = len(fake.calls)
    fake.gate.set()

    status = lambda oid: client.get(f"/api/v1/observations/{oid}").json()  # noqa: E731
    wait_for(lambda: status(queued[-1])["status"] == "processed")
    assert status(first)["status"] == "processed"
    assert [status(o)["status"] for o in queued[:-1]] == ["merged"] * 3
    assert status(queued[0])["result"]["merged_into"] == queued[-1]

    merged_calls = fake.calls[calls_before:]
    assert len(merged_calls) == 1 and "4 consecutive events" in merged_calls[0]["note"]
    assert merged_calls[0]["frames"] == ["before.jpg", "mid.jpg", "after.jpg"]

    mems = client.get("/api/v1/memories", params={"device_id": "cam-busy"}).json()
    assert len(mems) == 2 and mems[0]["summary"] == "A person moved around the desk for a while."
    device = client.get("/api/v1/devices/cam-busy").json()
    assert device["merged_count"] == 3 and device["pending_count"] == 0


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
