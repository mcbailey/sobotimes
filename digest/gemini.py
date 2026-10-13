"""Thin client for the Gemini Interactions API (REST, standard library only).

Docs: https://ai.google.dev/gemini-api/docs/interactions-overview
Every call runs with background=true and is polled to completion, which keeps
long video jobs from hitting HTTP timeouts.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from . import http

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    """A call failed in a way that should count as an attempt."""


class RateLimited(GeminiError):
    """Quota or rate limit hit (HTTP 429). Stop for today; don't blame the video."""


@dataclass
class Result:
    text: str
    usage: dict = field(default_factory=dict)
    interaction_id: str = ""

    def json(self) -> dict:
        return parse_json_text(self.text)


class InteractionsClient:
    def __init__(
        self,
        api_key: str,
        *,
        api_revision: str = "",
        base_url: str = BASE_URL,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        if not api_key:
            raise GeminiError("GEMINI_API_KEY is not set")
        self.api_key = api_key
        self.api_revision = api_revision
        self.base_url = base_url.rstrip("/")
        self.sleep = sleep
        self.clock = clock

    # --- raw calls -----------------------------------------------------------
    def _headers(self) -> dict:
        h = {"x-goog-api-key": self.api_key}
        if self.api_revision:
            h["Api-Revision"] = self.api_revision
        return h

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            raw = http.request(
                method,
                f"{self.base_url}/{path}",
                headers=self._headers(),
                body=body,
                timeout=120,
                sleep=self.sleep,
            )
        except http.HTTPError as e:
            if e.status == 429:
                raise RateLimited(e.message) from None
            raise GeminiError(f"{e.status}: {e.message}") from None
        except OSError as e:
            raise GeminiError(f"network error: {e}") from None
        return json.loads(raw) if raw else {}

    def create(self, body: dict) -> dict:
        return self._call("POST", "interactions", body)

    def get(self, interaction_id: str) -> dict:
        return self._call("GET", f"interactions/{interaction_id}")

    def cancel(self, interaction_id: str) -> None:
        try:
            self._call("POST", f"interactions/{interaction_id}/cancel", {})
        except GeminiError:
            pass

    # --- high level ------------------------------------------------------------
    def run(
        self,
        *,
        model: str,
        input: list | str,
        system_instruction: str | None = None,
        schema: dict | None = None,
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
        timeout_s: float = 1200,
    ) -> Result:
        body: dict = {"model": model, "input": input, "background": True}
        if system_instruction:
            body["system_instruction"] = system_instruction
        if schema:
            body["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            }
        gen: dict = {}
        if max_output_tokens:
            gen["max_output_tokens"] = int(max_output_tokens)
        if thinking_level:
            gen["thinking_level"] = thinking_level
        if gen:
            body["generation_config"] = gen

        inter = self.create(body)
        iid = inter.get("id", "")
        deadline = self.clock() + timeout_s
        delay = 10.0
        while inter.get("status") == "in_progress":
            if self.clock() > deadline:
                self.cancel(iid)
                raise GeminiError(f"timed out after {int(timeout_s)}s (interaction {iid})")
            self.sleep(delay)
            delay = min(60.0, delay * 1.5)  # gentle polling; free tier has request caps
            inter = self.get(iid)

        status = inter.get("status")
        if status not in (None, "completed"):
            err = inter.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            if isinstance(err, dict) and (err.get("code") == 429 or "RESOURCE_EXHAUSTED" in str(err)):
                raise RateLimited(msg or "rate limited")
            raise GeminiError(f"interaction {status}: {msg or 'no details'}")
        return Result(text=output_text(inter), usage=inter.get("usage") or {}, interaction_id=iid)


def output_text(inter: dict) -> str:
    """The text of the final model output (REST equivalent of the SDK's output_text)."""
    if isinstance(inter.get("output_text"), str) and inter["output_text"]:
        return inter["output_text"]
    for step in reversed(inter.get("steps") or []):
        if step.get("type") == "model_output":
            texts = [c.get("text", "") for c in step.get("content") or [] if c.get("type") == "text"]
            if any(texts):
                return "".join(texts)
    for out in reversed(inter.get("outputs") or []):  # older response shape
        if out.get("type") == "text" and out.get("text"):
            return out["text"]
    raise GeminiError("the response contained no text output")


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_json_text(text: str) -> dict:
    cleaned = _FENCE.sub("", text.strip())
    try:
        obj = json.loads(cleaned)
    except ValueError as e:
        raise GeminiError(f"model returned invalid JSON: {e}") from None
    if not isinstance(obj, dict):
        raise GeminiError("model returned JSON that is not an object")
    return obj


def video_part(video_id: str, processing: str = "agentic", fps: float = 0.2) -> dict:
    part: dict = {"type": "video", "uri": f"https://www.youtube.com/watch?v={video_id}"}
    if processing == "static":
        part["processing"] = {"type": "static", "fps": fps}
    else:
        part["processing"] = "agentic"
    return part
