from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import devices, evidence, jobs, memories, observations, query
from backend.config import settings
from backend.db.database import init_db
from backend.services import model_manager, video_processor, worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    worker.start()
    video_processor.start()
    model_manager.start()
    logging.getLogger("backend").info(
        "Vision model %s at %s", settings.vision_model, settings.vision_base_url)
    yield


app = FastAPI(title="Visual Memory API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (devices, observations, jobs, memories, query, evidence):
    app.include_router(module.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"ok": True, "vision_base_url": settings.vision_base_url, "model": model_manager.status()}
