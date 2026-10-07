"""VisionService: turns observation frames into a structured event via a VLM.

Talks to any OpenAI-compatible endpoint (Ollama, vLLM, OpenRouter, DashScope...).
The model is Qwen3-VL by default; nothing here is Ollama-specific.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Literal

import cv2
import numpy as np
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    OpenAI,
)
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.config import settings

log = logging.getLogger(__name__)

EVENT_TYPES = (
    "object_moved", "object_added", "object_removed", "person_activity",
    "scene_change", "baseline", "other",
)


class VisionUnavailable(RuntimeError):
    """The model endpoint could not be reached; the observation should be retried."""


class ObjectChange(BaseModel):
    name: str
    action: Literal["moved", "added", "removed", "present", "used", "other"] = "other"
    location_before: str | None = None
    location_after: str | None = None

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, v):
        v = (v or "other").lower().strip()
        return v if v in ("moved", "added", "removed", "present", "used") else "other"

    @field_validator("location_before", "location_after", mode="before")
    @classmethod
    def _loc(cls, v):
        if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a", "unknown")):
            return None
        return str(v).strip()


class VisionResult(BaseModel):
    is_meaningful: bool
    event_type: str = "other"
    summary: str
    objects: list[ObjectChange] = Field(default_factory=list)
    confidence: float = 0.5

    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type(cls, v):
        v = (v or "other").lower().strip().replace(" ", "_")
        return v if v in EVENT_TYPES else "other"

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


class Answer(BaseModel):
    answer: str
    memory_ids: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = (
    "You are the memory module of a small home camera. You look at camera frames and record "
    "what changed, so the owner can later ask questions such as 'Where did I leave my keys?'. "
    "Be concrete and factual, never invent objects you cannot see. Reply with a single JSON object only."
)

SCHEMA_HINT = """Reply with JSON exactly in this shape:
{
  "is_meaningful": true | false,
  "event_type": "object_moved" | "object_added" | "object_removed" | "person_activity" | "scene_change" | "baseline" | "other",
  "summary": "one short sentence a person would want to remember",
  "objects": [{"name": "keys", "action": "moved" | "added" | "removed" | "present" | "used", "location_before": "on the desk" | null, "location_after": "on the shelf" | null}],
  "confidence": 0.0-1.0
}"""

CHANGE_PROMPT = """These frames come from a fixed camera.
{frame_legend}
Time: {when}.

Compare BEFORE and AFTER. Which objects were placed, removed or moved, and where are they now?
Mention people only if what they did matters (e.g. "someone took the backpack").
Use short, concrete locations relative to furniture or landmarks ("on the desk next to the laptop").
Set is_meaningful=false if nothing worth remembering changed: lighting, shadows, camera noise,
a person just passing by, or tiny shifts of the same object.
"""

BASELINE_PROMPT = """This is the first view from a fixed camera (time: {when}).
Make an inventory of notable everyday objects a person might later look for (keys, phone, wallet,
glasses, mug, bottle, bag, laptop, remote, headphones, books, tools...) and where each one is.
Use event_type "baseline", action "present" and put each object's position in location_after.
Set is_meaningful=false only if the image is black, blurred or shows no recognizable objects.
"""

ANSWER_PROMPT = """You answer questions about what a home camera has seen, using ONLY the memories below
(oldest first). Each memory has an id in square brackets.

{memories}

Question: {question}

Rules: objects can be moved several times, so use the MOST RECENT memory that mentions the object.
Mention when it was seen. Speak as the camera ("I last saw..."). If the memories do not contain
the answer, reply that you haven't seen it and return an empty memory_ids list.
Reply with JSON: {{"answer": "one or two sentences", "memory_ids": ["ids of the memories you used"]}}"""

FRAME_LEGEND = {
    "before.jpg": "BEFORE — the stable scene before the change",
    "mid.jpg": "DURING — the moment of most activity",
    "after.jpg": "AFTER — the stable scene after the change",
}


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles <think>, code fences, chatter)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


def _to_data_url(jpeg: bytes, max_side: int) -> str:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("invalid image")
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


class VisionService:
    def __init__(self):
        self.client = OpenAI(
            base_url=settings.vision_base_url,
            api_key=settings.vision_api_key or "none",
            timeout=settings.vision_timeout,
            max_retries=0,
        )
        self.model = settings.vision_model
        self._json_mode = True

    # --- low level ------------------------------------------------------------

    # Generous budgets: "thinking" model variants spend tokens on hidden reasoning first.
    def _chat(self, messages: list[dict], max_tokens: int = 2048) -> str:
        kwargs = dict(model=self.model, messages=messages, temperature=0.1, max_tokens=max_tokens)
        try:
            if self._json_mode:
                try:
                    resp = self.client.chat.completions.create(
                        **kwargs, response_format={"type": "json_object"}
                    )
                except BadRequestError as exc:
                    if "response_format" not in str(exc) and "json" not in str(exc).lower():
                        raise
                    log.info("Endpoint rejected response_format; falling back to prompt-only JSON")
                    self._json_mode = False
                    resp = self.client.chat.completions.create(**kwargs)
            else:
                resp = self.client.chat.completions.create(**kwargs)
        # NotFoundError: Ollama answers 404 while the model is still being downloaded.
        except (APIConnectionError, APITimeoutError, InternalServerError, NotFoundError) as exc:
            raise VisionUnavailable(f"{type(exc).__name__}: {exc}") from exc
        return resp.choices[0].message.content or ""

    def _chat_json(self, messages: list[dict], model_cls, max_tokens: int = 2048):
        reply = self._chat(messages, max_tokens)
        try:
            return model_cls.model_validate(extract_json(reply))
        except (ValueError, ValidationError) as exc:
            log.warning("Invalid JSON from model (%s); asking for a repair", exc)
            repair = messages + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": "That was not valid JSON for the requested shape. "
                                            "Reply with only the corrected JSON object."},
            ]
            return model_cls.model_validate(extract_json(self._chat(repair, max_tokens)))

    # --- public API -----------------------------------------------------------

    def analyze(self, obs_type: str, frames: list[tuple[str, bytes]], when: str) -> VisionResult:
        if obs_type == "baseline":
            text = BASELINE_PROMPT.format(when=when)
        else:
            legend = "\n".join(
                f"Image {i + 1}: {FRAME_LEGEND.get(name, name)}" for i, (name, _) in enumerate(frames)
            )
            text = CHANGE_PROMPT.format(frame_legend=legend, when=when)

        content: list[dict] = [{"type": "text", "text": text + "\n" + SCHEMA_HINT}]
        for _, data in frames:
            content.append({
                "type": "image_url",
                "image_url": {"url": _to_data_url(data, settings.vision_image_max_side)},
            })
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        result = self._chat_json(messages, VisionResult)
        if obs_type == "baseline":
            result.event_type = "baseline"
        return result

    def answer(self, question: str, memory_lines: list[str]) -> Answer:
        prompt = ANSWER_PROMPT.format(memories="\n".join(memory_lines), question=question)
        return self._chat_json([{"role": "user", "content": prompt}], Answer)


_service: VisionService | None = None


def get_vision() -> VisionService:
    global _service
    if _service is None:
        _service = VisionService()
    return _service
