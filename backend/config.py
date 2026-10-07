from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    storage_dir: Path = field(default_factory=lambda: Path(os.getenv("STORAGE_DIR", "./storage")).resolve())
    vision_base_url: str = os.getenv("VISION_BASE_URL", "http://localhost:11434/v1")
    vision_model: str = os.getenv("VISION_MODEL", "qwen3-vl:4b-instruct")
    vision_api_key: str = os.getenv("VISION_API_KEY", "ollama")
    vision_timeout: float = float(os.getenv("VISION_TIMEOUT", "180"))
    vision_image_max_side: int = int(os.getenv("VISION_IMAGE_MAX_SIDE", "768"))
    cors_origins: tuple[str, ...] = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()
    )
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "1024"))
    device_online_seconds: int = 30

    @property
    def db_path(self) -> Path:
        return self.storage_dir / "visual_memory.db"

    @property
    def evidence_dir(self) -> Path:
        return self.storage_dir / "evidence"

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"


settings = Settings()
