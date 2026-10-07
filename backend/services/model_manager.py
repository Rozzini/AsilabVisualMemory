"""Makes sure the vision model exists when it is served by Ollama.

On startup it checks Ollama's model list and, if the configured model is missing, pulls
it through Ollama's REST API while exposing progress (shown by the portal via /health).
For hosted / vLLM endpoints it does nothing and reports "external".
"""

from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import urlparse

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

OLLAMA_PORT = 11434
RECHECK_S = 15.0

_state: dict = {"status": "checking", "progress": None, "message": None}
_lock = threading.Lock()
_thread: threading.Thread | None = None


def ollama_root(base_url: str | None = None) -> str | None:
    """'http://localhost:11434/v1' -> 'http://localhost:11434'; None if not an Ollama URL."""
    u = urlparse(base_url or settings.vision_base_url)
    if u.port != OLLAMA_PORT or not u.hostname:
        return None
    return f"{u.scheme}://{u.hostname}:{u.port}"


def full_name(model: str) -> str:
    return model if ":" in model else f"{model}:latest"


def status() -> dict:
    with _lock:
        return {"name": settings.vision_model, **_state}


def _set(status_: str, progress: float | None = None, message: str | None = None) -> None:
    with _lock:
        _state.update(status=status_, progress=progress, message=message)


class PullProgress:
    """Aggregates Ollama's streamed pull events (one per layer) into a single fraction."""

    def __init__(self):
        self.layers: dict[str, tuple[int, int]] = {}
        self.done = False

    def update(self, event: dict) -> None:
        if "error" in event:
            raise RuntimeError(event["error"])
        if event.get("status") == "success":
            self.done = True
        digest, total = event.get("digest"), event.get("total")
        if digest and total:
            self.layers[digest] = (int(event.get("completed") or 0), int(total))

    @property
    def fraction(self) -> float:
        total = sum(t for _, t in self.layers.values())
        if self.done:
            return 1.0
        return sum(c for c, _ in self.layers.values()) / total if total else 0.0


def _model_present(client: httpx.Client, root: str) -> bool:
    tags = client.get(f"{root}/api/tags").json().get("models", [])
    wanted = full_name(settings.vision_model)
    return any(wanted in (m.get("name"), m.get("model")) for m in tags)


def _pull(client: httpx.Client, root: str) -> None:
    model = settings.vision_model
    log.info("Vision model %s not found in Ollama, downloading it (first run only)…", model)
    _set("downloading", 0.0, f"Downloading {model}")
    progress = PullProgress()
    last_logged = -1
    with client.stream("POST", f"{root}/api/pull", json={"model": model},
                       timeout=httpx.Timeout(10.0, read=None)) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.strip():
                continue
            progress.update(json.loads(line))
            pct = int(progress.fraction * 100)
            _set("downloading", round(progress.fraction, 3), f"Downloading {model}")
            if pct // 10 > last_logged:
                last_logged = pct // 10
                log.info("Downloading %s: %d%%", model, pct)
    if not progress.done:
        raise RuntimeError("download ended unexpectedly")
    log.info("Vision model %s is ready", model)


def _run(root: str) -> None:
    from backend.services import worker

    with httpx.Client(timeout=5.0) as client:
        while True:
            try:
                if _model_present(client, root):
                    if _state["status"] != "ready":
                        _set("ready")
                        worker.requeue_pending()  # analyse anything that waited for the model
                else:
                    _pull(client, root)
                    continue  # re-check right away
            except httpx.HTTPError:
                _set("unavailable", message=f"Ollama is not reachable at {root}")
            except (RuntimeError, ValueError) as exc:
                log.error("Could not download %s: %s", settings.vision_model, exc)
                _set("error", message=f"Could not download {settings.vision_model}: {exc}")
                time.sleep(60)
            time.sleep(RECHECK_S)


def start() -> None:
    global _thread
    root = ollama_root()
    if root is None:
        _set("external", message="Model served by an external endpoint")
        return
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_run, args=(root,), daemon=True, name="model-manager")
    _thread.start()
