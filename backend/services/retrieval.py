"""Memory retrieval: SQLite FTS5 keyword search + LLM answer synthesis (with a template fallback)."""

from __future__ import annotations

import logging
import re

from backend.db.database import connect
from backend.services.memory import MEMORY_SELECT, memory_to_dict

log = logging.getLogger(__name__)

STOPWORDS = set("""
a an the i me my mine we our you your he she it its they them their is are was were be been being
am do does did doing have has had what where when which who whom why how this that these those
there here of in on at to from by for with about into onto over under again then once all any
both each few more most other some such no nor not only own same so than too very can will just
should now did leave left put last see seen saw find found lost place placed get got go went
please tell show know any anything something thing things today yesterday ever
""".split())

TOP_K = 8
FALLBACK_K = 10


def build_fts_query(question: str) -> str | None:
    """'Where did I leave my keys?' -> 'keys'. Porter stemming in the index handles plurals."""
    terms = [t for t in re.findall(r"[a-z0-9]+", question.lower()) if t not in STOPWORDS and len(t) > 1]
    if not terms:
        return None
    return " OR ".join(dict.fromkeys(terms))  # dedupe, keep order


def _scope_sql(device_id: str | None, job_id: str | None) -> tuple[str, list]:
    if device_id:
        return " AND m.device_id = ?", [device_id]
    if job_id:
        return " AND m.job_id = ?", [job_id]
    return "", []


def search(question: str, device_id: str | None = None, job_id: str | None = None) -> list[dict]:
    scope, params = _scope_sql(device_id, job_id)
    fts = build_fts_query(question)
    rows = []
    with connect() as conn:
        if fts:
            rows = conn.execute(
                MEMORY_SELECT
                + " JOIN memories_fts f ON f.memory_id = m.id WHERE memories_fts MATCH ?"
                + scope + " ORDER BY bm25(memories_fts) LIMIT ?",
                [fts, *params, TOP_K],
            ).fetchall()
        if not rows:  # nothing matched: give the model the most recent context instead
            rows = conn.execute(
                MEMORY_SELECT + " WHERE 1=1" + scope + " ORDER BY m.timestamp DESC LIMIT ?",
                [*params, FALLBACK_K],
            ).fetchall()
    memories = [memory_to_dict(r) for r in rows]
    memories.sort(key=lambda m: (m["timestamp"], m["video_offset_s"] or 0))  # oldest first
    return memories


def _describe_time(m: dict) -> str:
    if m["video_offset_s"] is not None:
        mm, ss = divmod(int(m["video_offset_s"]), 60)
        return f"video {mm:02d}:{ss:02d}"
    return m["timestamp"][:19].replace("T", " ") + " UTC"


def _memory_line(m: dict) -> str:
    objs = []
    for o in m["objects"]:
        loc = " → ".join(x for x in (o.get("location_before"), o.get("location_after")) if x)
        objs.append(f"{o['name']} ({o['action']}{': ' + loc if loc else ''})")
    obj_text = f" Objects: {', '.join(objs)}." if objs else ""
    return f"[{m['id']}] {_describe_time(m)}: {m['summary']}{obj_text}"


def answer(question: str, device_id: str | None = None, job_id: str | None = None) -> dict:
    from backend.services.vision import get_vision

    memories = search(question, device_id, job_id)
    if not memories:
        return {"answer": "I don't have any memories yet.", "memories": [], "used_llm": False}

    try:
        result = get_vision().answer(question, [_memory_line(m) for m in memories])
        by_id = {m["id"]: m for m in memories}
        cited = [by_id[i] for i in result.memory_ids if i in by_id]
        return {"answer": result.answer, "memories": cited, "used_llm": True}
    except Exception as exc:
        log.warning("Answer synthesis failed (%s); using template answer", exc)
        latest = memories[-1]
        return {
            "answer": f"Most relevant memory ({_describe_time(latest)}): {latest['summary']}",
            "memories": [latest],
            "used_llm": False,
        }
