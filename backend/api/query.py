from __future__ import annotations

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from backend.models.schemas import QueryRequest
from backend.services import retrieval

router = APIRouter(tags=["query"])


@router.post("/query")
async def query(body: QueryRequest):
    return await run_in_threadpool(retrieval.answer, body.query, body.device_id, body.job_id)
