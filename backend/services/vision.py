"""VisionService: turns observation frames into a structured event via a VLM.

Talks to any OpenAI-compatible endpoint (Ollama, vLLM, OpenRouter, DashScope...).
The model is Qwen3-VL by default; nothing here is Ollama-specific.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
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
    "person_entered", "person_left", "person_activity",
    "object_added", "object_removed", "object_moved",
    "lighting_change", "camera_moved", "scene_change", "baseline", "other",
)
OBJECT_ACTIONS = ("moved", "added", "removed", "present", "held", "used")


class VisionUnavailable(RuntimeError):
    """The model endpoint could not be reached; the observation should be retried."""


class ObjectChange(BaseModel):
    name: str
    action: Literal["moved", "added", "removed", "present", "held", "used", "other"] = "other"
    location_before: str | None = None
    location_after: str | None = None

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, v):
        v = (v or "other").lower().strip()
        return v if v in OBJECT_ACTIONS else "other"

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
    "You are the memory module of a home camera. You look at camera frames and write down what "
    "happened in the scene: people coming and going and what they do, objects being added, removed "
    "or moved, lights switching on or off, the camera being moved. The owner later asks questions "
    "such as 'Where did I leave my keys?' or 'When did someone come in?'. Be concrete and factual, "
    "never invent things you cannot see. Reply with a single JSON object only."
)

SCHEMA_HINT = """Reply with JSON exactly in this shape:
{
  "is_meaningful": true | false,
  "event_type": "person_entered" | "person_left" | "person_activity" | "object_added" | "object_removed" | "object_moved" | "lighting_change" | "camera_moved" | "scene_change" | "baseline" | "other",
  "summary": "one short sentence describing what happened",
  "objects": [{"name": "keys", "action": "moved" | "added" | "removed" | "present" | "held" | "used", "location_before": "on the desk" | null, "location_after": "on the shelf" | null}],
  "confidence": 0.0-1.0
}
Keep it short: at most 5 objects, only the ones involved in what happened (for an inventory: the most notable ones, at most 8)."""

CHANGE_PROMPT = """These frames come from a home camera.
{frame_legend}
Time: {when}.
{previous}
Describe what happened. Look for:
- people: someone entered, left, or picked up / put down / held up / used an object (the DURING frame shows the action);
- objects added, removed or moved, and where they are now;
- lighting: lights switched on or off, the room got much darker or brighter;
- the camera itself moved (the whole view is different): use event_type "camera_moved" and list the notable objects now visible, with their locations in location_after.
Use short, concrete locations relative to furniture or landmarks ("on the desk next to the laptop").
{dismiss_rule}
"""

CHANGE_DISMISS_RULE = (
    "Set is_meaningful=false ONLY if nothing visibly happened (camera noise, compression, tiny shifts of "
    "the same thing) or the frames just repeat the previous memory with nothing new."
)

ACTIVITY_NOTE = (
    "IMPORTANT: something moved in front of the camera between BEFORE and AFTER, even if those two look "
    "the same. Describe what happens in the DURING image (e.g. 'A person walked past the desk', "
    "'Someone held up a mug')."
)
ACTIVITY_DISMISS_RULE = (
    "For this event, set is_meaningful=false only if the DURING image shows nothing but camera noise; "
    "BEFORE and AFTER being identical is expected and is NOT a reason to dismiss."
)

BASELINE_PROMPT = """This is the first view from this camera (time: {when}).
Describe the scene in one sentence (including any people) and make an inventory of notable everyday
objects a person might later look for (keys, phone, wallet, glasses, mug, bottle, bag, laptop, remote,
headphones, books, tools...) and where each one is.
Use event_type "baseline", action "present" and put each object's position in location_after.
Set is_meaningful=false only if the image is black, blurred or shows nothing recognizable.
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
    "before.jpg": "BEFORE — the scene before",
    "mid.jpg": "DURING — the moment of most activity",
    "after.jpg": "AFTER — the scene now",
}


def measured_facts(scores: dict | None) -> dict:
    """Whole-image changes measured by the detector: lights off/on and camera moved.

    Small VLMs focus on objects and tend to miss these, so they are measured on the device
    (brightness, verified view shift) and treated as facts that override the model's verdict.
    """
    facts: dict = {"lighting": None, "camera_moved": False}
    if not scores:
        return facts
    before, after = scores.get("brightness_before"), scores.get("brightness_after")
    if before and after is not None:
        ratio = after / before
        facts["lighting"] = "off" if ratio < 0.6 else "on" if ratio > 1.6 else None
        facts["brightness"] = (before, after)
    facts["camera_moved"] = scores.get("view_shift", 0) > 0.06 and scores.get("view_shift_explains", 0) > 0.6
    facts["view_shift"] = scores.get("view_shift", 0)
    return facts


def measurement_hints(scores: dict | None) -> str:
    """The measured facts as prompt lines."""
    facts = measured_facts(scores)
    hints = []
    if facts["lighting"]:
        before, after = facts["brightness"]
        word, cause = ("darker", "switched off or dimmed") if facts["lighting"] == "off" else ("brighter", "switched on")
        hints.append(f"the whole image got much {word} (brightness {before:.0%} -> {after:.0%}); "
                     f"lights were probably {cause}")
    if facts["camera_moved"]:
        hints.append(f"the whole view shifted by about {facts['view_shift']:.0%} of its width; "
                     "the camera itself was probably moved or turned")
    return "".join(f"Measured by the camera: {h}.\n" for h in hints)


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

    def analyze(
        self,
        obs_type: str,
        frames: list[tuple[str, bytes]],
        when: str,
        previous: str | None = None,
        scores: dict | None = None,
        note: str | None = None,
    ) -> VisionResult:
        """`previous`: the latest memory from the same source, so the model can skip repeats.
        `scores`: the detector's measurements (brightness, view shift) for this event.
        `note`: extra context, e.g. that several queued events were merged into this one."""
        started = time.monotonic()
        result = self._describe(obs_type, frames, when, previous, scores, note)

        facts = measured_facts(scores)
        if obs_type != "baseline" and facts["camera_moved"]:
            # New view: record it as such and inventory what is visible now.
            after = [f for f in frames if f[0] == "after.jpg"] or frames[-1:]
            inventory = self._describe("baseline", after, when)
            result = VisionResult(
                is_meaningful=True, event_type="camera_moved",
                summary=f"The camera was moved. {inventory.summary}",
                objects=inventory.objects, confidence=inventory.confidence,
            )
        elif obs_type != "baseline" and facts["lighting"] and result.event_type != "lighting_change":
            note = ("The lights were switched off (the room got much darker)." if facts["lighting"] == "off"
                    else "The lights were switched on (the room got much brighter).")
            if result.is_meaningful:
                result.summary = f"{result.summary} {note}"
            else:
                result = VisionResult(is_meaningful=True, event_type="lighting_change", summary=note,
                                      confidence=0.9)

        log.info("Analysed %s (%d frame(s)) in %.1fs", obs_type, len(frames), time.monotonic() - started)
        return result

    def _describe(
        self,
        obs_type: str,
        frames: list[tuple[str, bytes]],
        when: str,
        previous: str | None = None,
        scores: dict | None = None,
        note: str | None = None,
    ) -> VisionResult:
        """One model call: what does the VLM see in these frames?"""
        baseline = obs_type == "baseline"
        if baseline:
            text = BASELINE_PROMPT.format(when=when)
        else:
            legend = "\n".join(
                f"Image {i + 1}: {FRAME_LEGEND.get(name, name)}" for i, (name, _) in enumerate(frames)
            )
            activity = obs_type == "activity"
            if activity:
                legend += "\n" + ACTIVITY_NOTE
            if note:
                legend += "\n" + note
            prev = f"Previous memory from this camera: {previous}\n" if previous else ""
            text = CHANGE_PROMPT.format(
                frame_legend=legend, when=when, previous=prev + measurement_hints(scores),
                dismiss_rule=ACTIVITY_DISMISS_RULE if activity else CHANGE_DISMISS_RULE,
            )

        content: list[dict] = [{"type": "text", "text": text + "\n" + SCHEMA_HINT}]
        for name, data in frames:
            # DURING only has to show the action, so it is sent smaller (fewer image tokens).
            max_side = settings.vision_mid_image_max_side if name == "mid.jpg" else settings.vision_image_max_side
            content.append({"type": "image_url", "image_url": {"url": _to_data_url(data, max_side)}})
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        # Output tokens are a large part of the latency on Apple Silicon / CPU: keep answers short.
        max_tokens = max(settings.vision_max_tokens, 1024) if baseline else settings.vision_max_tokens
        result = self._chat_json(messages, VisionResult, max_tokens)
        if baseline:
            result.event_type = "baseline"
        return result

    def answer(self, question: str, memory_lines: list[str]) -> Answer:
        prompt = ANSWER_PROMPT.format(memories="\n".join(memory_lines), question=question)
        return self._chat_json([{"role": "user", "content": prompt}], Answer, settings.vision_max_tokens)


_service: VisionService | None = None


def get_vision() -> VisionService:
    global _service
    if _service is None:
        _service = VisionService()
    return _service
