"""visual-memory-agent — the device.

capture → sample (~1/s) → rolling JPEG buffer → change detection → outbox → upload
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

import psutil

from agent.capture.base import CaptureSource
from agent.capture.video_file import VideoFileSource
from agent.capture.webcam import WebcamSource
from agent.config import AgentConfig, parse_args
from agent.uploader.client import ApiClient
from agent.uploader.queue import DiskQueue, Uploader
from detection import ChangeDetector, DetectedEvent, RollingBuffer, encode_jpeg, evidence_frames

log = logging.getLogger("agent")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def build_observation(
    cfg: AgentConfig, ev: DetectedEvent, buffer: RollingBuffer
) -> tuple[dict, list[tuple[str, bytes]]]:
    frames = evidence_frames(ev, buffer)
    metadata = {
        "device_id": cfg.device_id,
        "timestamp": iso(ev.after_ts),
        "observation_type": ev.type,
        "event_start": iso(ev.start_ts),
        "event_end": iso(ev.end_ts),
        "scores": ev.scores,
        "forced": ev.forced,
    }
    return metadata, frames


class Heartbeat(threading.Thread):
    def __init__(self, client: ApiClient, interval: float, stats_fn):
        super().__init__(daemon=True, name="heartbeat")
        self.client, self.interval, self.stats_fn = client, interval, stats_fn
        self.stopping = threading.Event()

    def run(self) -> None:
        while not self.stopping.is_set():
            try:
                self.client.heartbeat(self.stats_fn())
            except Exception as exc:
                log.debug("Heartbeat failed: %s", exc)
            self.stopping.wait(self.interval)


def open_source(cfg: AgentConfig) -> CaptureSource:
    if cfg.video is not None:
        return VideoFileSource(cfg.video, realtime=cfg.realtime)
    return WebcamSource(cfg.webcam or 0)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = parse_args(argv)

    client = ApiClient(cfg.server, cfg.device_id)
    queue = DiskQueue(cfg.outbox_dir, max_bytes=cfg.outbox_max_mb * 1024 * 1024)
    uploader = Uploader(queue, client)
    detector = ChangeDetector(cfg.detector)
    buffer = RollingBuffer(max_seconds=cfg.buffer_seconds)
    proc = psutil.Process(os.getpid())

    def stats() -> dict:
        return {
            **detector.stats.as_dict(),
            "uploaded": uploader.uploaded,
            "queued": len(queue.items()),
            "evicted": queue.evicted,
            "buffer_frames": len(buffer),
            "buffer_kb": buffer.size_bytes // 1024,
            "rss_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
        }

    try:
        client.register(cfg.name)
        log.info("Registered device %s with %s", cfg.device_id, cfg.server)
    except Exception as exc:
        log.warning("Server unreachable (%s); observations will be queued locally", exc)

    try:
        source = open_source(cfg)
    except RuntimeError as exc:
        log.error("%s", exc)
        client.close()
        return 1
    uploader.start()
    heartbeat = Heartbeat(client, cfg.heartbeat_interval, stats)
    heartbeat.start()
    log.info("Capturing from %s (1 sample / %.1fs)", cfg.video or f"webcam #{cfg.webcam or 0}",
             cfg.sample_interval)

    last_stats = time.time()
    try:
        for ts, frame in source.frames(cfg.sample_interval):
            buffer.add(ts, encode_jpeg(frame))
            ev = detector.process(ts, frame)
            if ev is not None:
                metadata, frames = build_observation(cfg, ev, buffer)
                queue.put(metadata, frames)
                uploader.wake.set()
                log.info("Event %s at %s scores=%s", ev.type, metadata["timestamp"], ev.scores)
            if cfg.stats and time.time() - last_stats > 10:
                log.info("stats %s", stats())
                last_stats = time.time()
    except KeyboardInterrupt:
        log.info("Stopping…")
    finally:
        source.close()
        heartbeat.stopping.set()
        if not uploader.flush(timeout=30):
            log.warning("%d observation(s) remain queued in %s; they will be sent on next start",
                        len(queue.items()), cfg.outbox_dir)
        uploader.stop()
        final = stats()
        try:
            client.heartbeat(final)
        except Exception:
            pass
        log.info("Final stats %s", final)
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
