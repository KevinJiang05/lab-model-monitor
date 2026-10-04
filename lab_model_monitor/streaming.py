"""Incremental Responses SSE reader; never waits for EOF after a terminal event."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any


def read_responses(stream: Any, progress: Callable[[dict], None] | None = None) -> dict:
    text = ""
    metadata: dict = {}
    count = 0
    data: list[str] = []

    def dispatch() -> dict | None:
        nonlocal text, metadata, count
        if not data:
            return None
        raw = "\n".join(data)
        data.clear()
        if raw == "[DONE]":
            return {**metadata, "output_text": text, "status": "incomplete"}
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("Invalid SSE event")
        count += 1
        kind = str(event.get("type", ""))
        response = event.get("response")
        if isinstance(response, dict):
            metadata.update({key: response[key] for key in ("id", "model", "usage") if key in response})
        if kind == "response.output_text.delta":
            text += str(event.get("delta") or "")
        terminal = kind in {"response.completed", "response.incomplete", "response.failed", "error"}
        if progress:
            progress({"response_text": text, "response_id": metadata.get("id", ""),
                      "returned_model": metadata.get("model", ""), "stream_event_count": count,
                      "last_event": kind, "received_characters": len(text), "terminal": terminal})
        if terminal:
            result = {**metadata, **(response if isinstance(response, dict) else {})}
            if not result.get("output_text") and not result.get("output"):
                result["output_text"] = text
            result["status"] = {"response.completed": "completed", "response.incomplete": "incomplete"}.get(kind, "failed")
            return result
        return None

    while True:
        line = stream.readline(2_000_001)
        if len(line) > 2_000_000:
            raise ValueError("SSE line too large")
        if not line:
            terminal = dispatch()
            return terminal or {**metadata, "output_text": text, "status": "incomplete"}
        decoded = line.decode("utf-8").rstrip("\r\n")
        if not decoded:
            terminal = dispatch()
            if terminal is not None:
                return terminal
        elif decoded.startswith("data:"):
            data.append(decoded[5:].lstrip(" "))
