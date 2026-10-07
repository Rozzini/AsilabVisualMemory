from __future__ import annotations

import argparse
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from detection import DetectorConfig


@dataclass
class AgentConfig:
    server: str
    device_id: str
    name: str
    webcam: int | None
    video: Path | None
    realtime: bool
    sample_interval: float
    outbox_dir: Path
    outbox_max_mb: int
    buffer_seconds: float
    heartbeat_interval: float
    stats: bool
    detector: DetectorConfig


def parse_args(argv: list[str] | None = None) -> AgentConfig:
    load_dotenv()
    p = argparse.ArgumentParser(
        prog="visual-memory-agent",
        description="Device agent: captures camera frames, detects scene changes locally "
        "and uploads observations to the Visual Memory server.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--webcam", nargs="?", const=0, type=int, metavar="INDEX",
                     help="capture from webcam (default index 0)")
    src.add_argument("--video", type=Path, help="replay a video file as the camera (testing)")
    p.add_argument("--realtime", action="store_true", help="pace --video like a live camera")
    p.add_argument("--server", default=os.getenv("API_URL", "http://localhost:8000"))
    p.add_argument("--device-id", default=os.getenv("DEVICE_ID", "webcam-01"))
    p.add_argument("--name", default=None, help="human readable device name")
    p.add_argument("--sample-interval", type=float, default=1.0, help="seconds between samples")
    p.add_argument("--outbox", type=Path, default=Path(os.getenv("AGENT_OUTBOX", "storage/agent_queue")))
    p.add_argument("--outbox-max-mb", type=int, default=1024)
    p.add_argument("--buffer-seconds", type=float, default=90.0)
    p.add_argument("--trigger", type=float, default=DetectorConfig.trigger_ratio,
                   help="changed-pixel ratio that starts an event (lower = more sensitive)")
    p.add_argument("--settle", type=int, default=DetectorConfig.settle_samples,
                   help="still samples required before an event is closed")
    p.add_argument("--stats", action="store_true", help="log resource usage and filter counters")
    a = p.parse_args(argv)

    return AgentConfig(
        server=a.server,
        device_id=a.device_id,
        name=a.name or f"{a.device_id} ({socket.gethostname()})",
        webcam=a.webcam,
        video=a.video,
        realtime=a.realtime,
        sample_interval=a.sample_interval,
        outbox_dir=a.outbox / a.device_id,
        outbox_max_mb=a.outbox_max_mb,
        buffer_seconds=a.buffer_seconds,
        heartbeat_interval=10.0,
        stats=a.stats,
        detector=DetectorConfig(trigger_ratio=a.trigger, settle_samples=a.settle),
    )
