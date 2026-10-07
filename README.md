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

**You need:** git and [Node.js 20+](https://nodejs.org). Everything else is downloaded on first run.

Use three terminals in the repo folder:

| | Windows | macOS / Linux |
|---|---|---|
| 1. Backend → http://localhost:8000/docs | `run-backend.cmd` | `bash run-backend.sh` |
| 2. Portal → http://localhost:3000 | `cd portal`, then `npm install`, then `npm run dev` | same |
| 3. Device (webcam) | `run-agent.cmd` | `bash run-agent.sh` |

**What the launchers download automatically** (about 4 GB on first run, mostly the model):
- [uv](https://docs.astral.sh/uv/), user-level with no admin or sudo. uv then installs Python 3.12 and every Python package into a local `.venv`.
- [Ollama](https://ollama.com), which runs the vision model locally. The backend launcher **asks before installing it**:
  - Windows: winget.
  - macOS: Homebrew, or the launcher prints the download link.
  - Linux: the official installer, which asks for sudo.
- The **Qwen3-VL model** (3.3 GB), downloaded by the backend itself on first start. The portal sidebar shows the progress. Anything the device sees in the meantime is queued and analysed once the download finishes.

Then put an object down, move it, take it away, and wait for the scene to be still for about 3 s. A memory appears in the portal under the device. Ask *"Where is my phone?"* on the device page.

**No webcam?** Run `uv run python scripts/make_demo_video.py`. It writes `demo.mp4`, a synthetic scene where keys move from the desk to the shelf. Upload it in the portal, or replay it as a device with `run-agent --video demo.mp4`.

**Agent options:**
- `--webcam 1` picks another camera.
- `--server http://<backend-ip>:8000` runs the device on another machine. Start the backend with `--host 0.0.0.0` for that.
- `--stats` logs RAM use and filter counters.
- `--trigger` sets detection sensitivity.
- `--device-id` and `--name` identify the device.

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

**Choosing a model.** All of these use the same code; only `.env` changes (the backend launcher creates `.env` from `.env.example`). With a non-Ollama endpoint, the launcher skips installing Ollama.

| Setup | `.env` | When |
|---|---|---|
| Ollama `qwen3-vl:4b-instruct` (default) | as shipped | any machine; ~1.5 s per event on an RTX 4080, CPU works (much slower) |
| Ollama `qwen3-vl:8b-instruct` | `VISION_MODEL=qwen3-vl:8b-instruct` | GPU with ≥ 8 GB VRAM, better spatial reasoning |
| Hosted (OpenRouter, DashScope…) | `VISION_BASE_URL`, `VISION_MODEL=qwen/qwen3-vl-8b-instruct`, `VISION_API_KEY` | weak laptop, no local model |
| vLLM (Linux + NVIDIA) | `VISION_BASE_URL=http://gpu:8000/v1`, `VISION_MODEL=Qwen/Qwen3-VL-8B-Instruct-FP8` | production-style GPU server |

**Tests.** `uv run pytest` runs the detector state machine, JSON parsing, model-download progress and both pipelines end to end, using a fake model. CI (`.github/workflows/ci.yml`) runs the launchers on clean Windows, macOS and Linux machines, followed by an agent → backend smoke test and the portal build.

---

## What I built

- **Device agent** (`agent/`, deps: OpenCV-headless, numpy, httpx).
  - Samples 1 frame/s, decoding only the sampled frames.
  - Keeps a bounded 90 s rolling buffer of JPEGs.
  - Runs a settle-based change detector.
  - Writes events to an on-disk **outbox**, which is drained in order with backoff and deleted on server confirmation.
  - Sends a heartbeat with filter and RAM stats. The agent uses about 60 MB of RAM.
- **Shared detector** (`detection/`). The same code is used by the device and by server-side upload processing.
- **Backend** (`backend/`, FastAPI + SQLite).
  - Observation ingest with validation.
  - A single analysis worker (one model, one GPU) and Qwen3-VL prompts that return strict JSON with repair/normalisation.
  - Memories indexed with **FTS5**, server-side video jobs with progress, and evidence serving.
- **Retrieval.** FTS5 keyword search scoped to a device, an upload or everything. The LLM then writes the answer from the timestamped memories and cites them. There is a template fallback if the model is down.
- **Portal** (`portal/`, Next.js 16).
  - Sidebar with **Devices** (online status, memory count) and **Uploaded videos** (status and progress).
  - Clicking one shows its **memory history**, with before/after thumbnails and an evidence viewer, plus an **Ask** box scoped to that source.
  - An overview page asks across all sources.

## Key decisions

- **What is a memory?** A *state change* in the scene: an object added, removed or moved, and where it ended up. The first frame of every session is a **baseline inventory**, so "where is X?" works even for objects that never moved.
- **Settle-based detection instead of naive frame diffs.** An event starts when the scene departs from the last stable state, and is closed only after the scene has been still for 3 samples. That gives the VLM a *clean* BEFORE/AFTER pair without the hand in the way. A person walking through and leaving produces nothing and is discarded on the device. Thresholds favour recall; the VLM decides what is meaningful (`is_meaningful=false` → dismissed, never a memory).
- **1 fps sampling instead of the 5 s in my initial sketch.** Diffing a 160 px grayscale frame costs almost nothing on 2 cores, and 5 s misses short actions.
- **The device never talks to the model.** It only says "potentially meaningful evidence here" over a tiny multipart protocol (`POST /observations`, `POST /devices/{id}/heartbeat`). An ESP32 could implement the same thing.
- **Storage is a bounded cache.** Rolling buffer (90 s, JPEG), outbox capped at 1 GB with oldest-first eviction, evidence at 1280 px / q80. No raw video is kept on the device.
- **OpenAI-compatible model API.** Ollama, vLLM and hosted Qwen are interchangeable, so reviewers don't need Docker or a big GPU.
- **Instruct, not "thinking", Qwen3-VL.** I measured both on the same events. The default `qwen3-vl:4b` tag reasons before answering: about 4.5 s per event, 6–23 s per question, and frequent invalid JSON. `4b-instruct` gave the same quality at about 1.4 s per event and under 1 s per question. Token budgets stay generous so thinking variants still work if configured.
- **SQLite + FTS5, no vector DB.** Questions about objects are keyword-heavy; porter stemming handles "key/keys". The LLM handles the temporal reasoning ("most recent memory wins").
- **No ffmpeg.** OpenCV wheels decode video on their own. Evidence is 2–3 JPEG keyframes rather than clips (cheaper to store and to send to the VLM).

## Assumptions

- The camera is **fixed**. A moving camera would make every frame a "change".
- One model call per event is acceptable latency: seconds on a GPU, tens of seconds on CPU. Analysis is asynchronous, so capture never blocks.
- Single user, local network, no authentication (POC).
- Upload timestamps are anchored at upload time plus the video offset; the portal shows `mm:ss` for uploads.

## What I'd do next

- Short H.264 evidence clips for ambiguous events, and a per-region detection mask (ignore windows and TVs).
- An object-level "last known location" table and an object timeline, with embeddings / hybrid search for fuzzy questions ("something to drink").
- Use the detector's `peak_motion` and a lightweight on-device person detector to tag *who* did something.
- Device auth (per-device keys), an evidence retention policy, and retry and visibility tools for failed analyses in the portal.
- A native ESP32-CAM firmware speaking the same protocol (JPEG snapshots + on-chip frame diff).
- Evaluation: a small labelled video set to tune thresholds and measure memory precision and recall.
