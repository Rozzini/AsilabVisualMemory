# Visual Memory POC

A camera device watches a scene, notices when something **changes**, and turns each change into a **structured memory** ("Keys were moved from the desk to the shelf"). Later you can browse the memory history or simply ask *"Where did I leave my keys?"*.

```
DEVICE (2 cores / 2 GB / no GPU)                     SERVER                                    PORTAL
webcam ─► sample 1 fps ─► rolling JPEG buffer        FastAPI ─► analysis worker ─► Qwen3-VL    Next.js
        ─► change detector (settle-based)             ▲   │        (OpenAI-compatible API)     • devices / uploaded videos
        ─► outbox on disk ─► POST /observations ──────┘   ▼                                    • memory history per source
                                                      SQLite + FTS5 (memories)  ◄── /query ─── • ask + evidence frames
PORTAL UPLOAD ─► POST /jobs ─► server decodes the video itself ─► same detector ─► same worker
```

There are two **independent** ways in:

1. **Device pipeline.** `visual-memory-agent --webcam` is the device. It captures from its own camera, filters locally and uploads only candidate events. The portal shows devices but never controls them.
2. **Upload pipeline.** You upload a video in the portal and the **server** processes it itself (no device involved).

Both feed the same analysis → memory → query path.

---

## How to run

**You need:** [Node.js 20+](https://nodejs.org). Everything else is downloaded on first run.

Open **three terminals** in the project folder and start them **in this order**:

1. **Backend.** It's ready when it prints `Uvicorn running on http://127.0.0.1:8000`.
   - Windows: `run-backend.cmd`
   - macOS / Linux: `bash run-backend.sh`
2. **Portal**, then open http://localhost:3000:
   ```bash
   cd portal
   npm install
   npm run dev
   ```
3. **Device** (webcam):
   - Windows: `run-agent.cmd`
   - macOS / Linux: `bash run-agent.sh`

**What the launchers download automatically** (about 4 GB on first run, mostly the model):
- [uv](https://docs.astral.sh/uv/), user-level with no admin or sudo. uv then installs Python 3.12 and every Python package into a local `.venv`.
- [Ollama](https://ollama.com), which runs the vision model locally. The backend launcher **asks before installing it**:
  - Windows: winget.
  - macOS: Homebrew, or the launcher prints the download link.
  - Linux: the official installer, which asks for sudo.
- The **Qwen3-VL model** (3.3 GB), downloaded by the backend itself on first start. The portal sidebar shows the progress. Anything the device sees in the meantime is queued and analysed once the download finishes.

Then try things in front of the camera:
- walk in and out
- hold up an object
- put something down, or move it
- switch the light off and on
- turn the camera

Each becomes a memory under the device a few seconds after the scene calms down. Ask *"Where is my phone?"* or *"When did someone come in?"* on the device page.

**No webcam?** Run `uv run python scripts/make_demo_video.py`. It writes `demo.mp4`, a synthetic scene where keys move from the desk to the shelf. Upload it in the portal, or replay it as a device with `run-agent --video demo.mp4`.

**Agent options:**
- `--webcam 1` picks another camera.
- `--server http://<backend-ip>:8000` runs the device on another machine. Start the backend with `--host 0.0.0.0` for that.
- `--stats` logs RAM use and filter counters.
- `--trigger` sets detection sensitivity.
- `--device-id` and `--name` identify the device.

**Memories arrive slowly?** The backend logs `Analysed visual_change (3 frame(s)) in X s` for every event, and the device page shows how many events are still being analysed.

When a live device produces events faster than the model can analyse them, the queued events are **merged** into one memory ("between 12:33 and 12:34 …"), so memories stay current instead of piling up. The device page shows how many were merged.

To speed things up:
- On a Mac, run `ollama ps` while it is busy. The PROCESSOR column should say `100% GPU`.
- Use a smaller model: `ollama pull qwen3-vl:2b-instruct` and `VISION_MODEL=qwen3-vl:2b-instruct`. Roughly 2× faster, weaker on small objects.
- Send smaller images: `VISION_IMAGE_MAX_SIDE=512` (default 640) or `VISION_MID_IMAGE_MAX_SIDE=256` (default 384).
- Use a hosted model instead (no GPU needed): any OpenAI-compatible endpoint serving Qwen3-VL works. Set `VISION_BASE_URL`, `VISION_MODEL` and `VISION_API_KEY` in `.env` (created by the backend launcher from `.env.example`), and the launcher then skips installing Ollama.

**macOS / Linux notes:**
- **macOS:** the first webcam run asks for camera permission for your terminal. If you denied it, enable it in *System Settings → Privacy & Security → Camera*. Apple Silicon runs the model on the GPU (fast); Intel Macs use the CPU (slow).
- **Linux:** webcam access may need your user in the `video` group.

<details>
<summary>Manual setup (without the launchers)</summary>

```bash
# install uv:  https://docs.astral.sh/uv/getting-started/installation/
# install Ollama: https://ollama.com/download
ollama pull qwen3-vl:4b-instruct
uv run uvicorn backend.main:app --port 8000      # backend
uv run visual-memory-agent --webcam              # device
cd portal && npm install && npm run dev          # portal
```
</details>

**Tests.** `uv run pytest` runs unit and end-to-end tests with a fake model. CI runs the launchers on Windows, macOS and Linux.

---

## What I built

- **Device agent** (`agent/`, deps: OpenCV-headless, numpy, httpx).
  - Samples 1 frame/s, decoding only the sampled frames.
  - Keeps a bounded 90 s rolling buffer of JPEGs.
  - Runs a settle-based change detector.
  - Writes events to an on-disk **outbox**, which is drained in order with backoff and deleted on server confirmation.
  - Sends a heartbeat with filter and RAM stats. The agent used 60–150 MB of RAM in testing (2 GB budget).
- **Shared detector** (`detection/`). The same code is used by the device and by server-side upload processing.
- **Backend** (`backend/`, FastAPI + SQLite).
  - Observation ingest with validation.
  - A single analysis worker (one model, one GPU) and Qwen3-VL prompts that return strict JSON with repair/normalisation.
  - Memories indexed with **FTS5**, server-side video jobs with progress, and evidence serving.
- **Retrieval.** FTS5 keyword search scoped to a device, an upload or everything. The LLM then writes the answer from the timestamped memories and cites them. There is a template fallback if the model is down.
- **Portal** (`portal/`, Next.js 16).
  - Sidebar with **Devices** (online status, memory count) and **Uploaded videos** (status and progress).
  - Clicking one shows its **memory history**, with before/during/after thumbnails and an evidence viewer, plus an **Ask** box scoped to that source.
  - An "events → memories · ignored · being analysed" summary, and a collapsible list of **ignored events** with the model's reason.
  - An overview page asks across all sources.

## Important assumptions

- The camera is **mostly fixed**. Moving it is recorded as a "camera moved" memory with a new inventory, but a camera that is constantly moving would make every frame a change.
- One model call per event is acceptable latency: seconds on a GPU, tens of seconds on CPU. Analysis is asynchronous, so capture never blocks.
- Single user, local network, no authentication (POC).
- Upload timestamps are anchored at upload time plus the video offset; the portal shows `mm:ss` for uploads.

## Major technical and product decisions

- **What is a memory?** **Anything that happens in the scene**:
  - people entering, leaving or doing something with an object
  - objects added, removed or moved, and where they ended up
  - lights switching on or off
  - the camera being moved (followed by a fresh inventory of the new view)

  The first frame of every session is a **baseline inventory**, so "where is X?" works even for objects that never moved. The model gets the previous memory as context and skips repeats ("person still sitting there").
- **Event detection that adapts to the camera.** Each sample is compared with the last *keyframe* (the scene as last reported) and with the previous sample (motion). The noise floor is the median motion of recent quiet samples, so a person sitting in view or a noisy sensor counts as "still" and real actions stand out. What happens next:
  - The scene settles in a different state about 2 s after an action → **visual_change**, with a clean BEFORE/AFTER pair and no hand in the way.
  - Something happened but the scene ended as it was (a walk-through, an object waved and put back) → **activity**. The DURING frame shows the action.
  - Activity that goes on → a checkpoint after 10 s, then less often (at most one per minute).

  Only noise-level blips are dropped on the device. The VLM decides what is worth remembering, and ignored events stay visible in the portal with the model's reason.
- **Bounded latency over completeness for live devices.** The first real-webcam test on an M1 Pro produced about one event every 10 s, faster than the model could analyse them, so a backlog grew. Three fixes:
  - The device drops motionless drift (webcam auto-exposure).
  - Checkpoints during long activity back off (10 → 20 → 40 → 60 s).
  - When a backlog still forms, the server merges the queued run into one analysis (first BEFORE, busiest DURING, last AFTER).

  Calls are also cheaper: a 384 px DURING frame and capped answer length. Uploaded videos are never merged.
- **Measured facts beat a small model's judgement.** In testing, the 4B VLM reliably missed whole-image changes and answered "no change" for lights off or a turned camera. So the detector measures them on the device: brightness before and after, and a whole-image shift (phase correlation, verified by checking that the shift explains the difference). The backend turns these into `lighting_change` / `camera_moved` memories, and a camera move triggers a fresh inventory of the new view.
- **One frame per second.** Comparing a 160 px grayscale frame with the previous one costs almost nothing on 2 cores, so the device can look every second and doesn't miss short actions.
- **The device never talks to the model.** It only says "potentially meaningful evidence here" over a tiny multipart protocol (`POST /observations`, `POST /devices/{id}/heartbeat`). An ESP32 could implement the same thing.
- **Storage is a bounded cache.** Rolling buffer (90 s, JPEG), outbox capped at 1 GB with oldest-first eviction, evidence at 1280 px / q80. No raw video is kept on the device.
- **OpenAI-compatible model API.** Ollama, vLLM and hosted Qwen are interchangeable, so the project runs without Docker or a big GPU.
- **SQLite + FTS5, no vector DB.** Questions about objects are keyword-heavy; porter stemming handles "key/keys". The LLM handles the temporal reasoning ("most recent memory wins").

## What I'd do next

- **Notifications for events the user cares about.** The user describes a rule in plain language, for example *"Tell me if the dog enters the room"* or *"Tell me if the baby starts moving"*. They get an e-mail or a phone push notification when it happens. Each new memory is already a text description of what happened, so the same model can check it against the user's rules. No new detection pipeline is needed.
- **Face recognition.** Recognise household members, so memories say *who* did something ("Anna took the keys") and rules can name people ("tell me when Anna comes home").
  - As a security measure: notify the user straight away when an **unrecognised person** enters, with the evidence frames attached.
- **Long-term vision:** ideally, a system like Sibyl in the anime *Psycho-Pass*, which detects a crime before it is even committed. That needs a huge amount of data from a unified surveillance system across a whole city or country, and the hardest part is defining "crime" correctly.
