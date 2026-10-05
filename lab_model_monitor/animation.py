"""HTML artifact extraction and a bounded, credential-free display projection."""
from __future__ import annotations

import hashlib
import re
from typing import Any

PROMPT = "创建一个 HTML，内容是 SVG 绘制一个绵羊驾驶潜艇的 2D 动画。"
INSTRUCTIONS = "请只返回一个完整、可独立打开的 HTML 文件，不要附加解释。"
VERSION = "sheep-submarine-html-v1"
MAX_HTML_BYTES = 512_000
MAX_SITE_RUNS = 20
MAX_SITE_RUN_BYTES = 1_500_000


def extract_html(text: str) -> str | None:
    """Remove only an enclosing Markdown fence; never repair the model output."""
    source = text.strip()
    fenced = re.fullmatch(r"```(?:html)?\s*\n([\s\S]*?)\n```", source, re.I)
    if fenced:
        source = fenced[1].strip()
    if (len(source.encode("utf-8")) > MAX_HTML_BYTES
            or not re.match(r"(?:<!doctype\s+html[^>]*>\s*)?<html\b", source, re.I)
            or not re.search(r"</html>\s*$", source, re.I)
            or not re.search(r"<svg\b", source, re.I)):
        return None
    return source


def projection(run: dict[str, Any]) -> dict[str, Any]:
    if run["contract"].get("prompt_version") != VERSION:
        raise ValueError("Not an animation run")
    samples = []
    for sample in run["samples"]:
        html = extract_html(sample["response_text"]) if sample["status"] == "generated" else None
        samples.append({
            **{key: sample.get(key) for key in ("requested_model", "returned_model", "status",
                "requested_at", "attempt", "elapsed_seconds", "input_tokens", "output_tokens", "total_tokens", "completion_status")},
            "html": html,
            "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest() if html else None,
            "http_status": next(iter(re.findall(r"HTTP(?:Error)?\s*[: ]?\s*([45]\d\d)\b", str(sample.get("error") or ""), re.I)), None),
        })
    return {"run_id": run["run_id"], "created_at": run["created_at"],
            "prompt": PROMPT, "instructions": INSTRUCTIONS,
            "reasoning_effort": run["contract"]["reasoning_effort"],
            "stream": run["contract"].get("stream", False),
            "max_output_tokens": run["contract"]["max_output_tokens"], "samples": samples}


def site_snapshot(store, now=None):
    """Keep 20 completed runs; each run fits its own D1 display row."""
    import json
    from datetime import UTC, datetime
    timestamp = now or datetime.now(UTC)
    payload = {"kind": "animation", "schema_version": 1,
               "synced_at": timestamp.isoformat(), "runs": []}
    for run in store.recent(prompt_version=VERSION, limit=MAX_SITE_RUNS, now=timestamp, completed_only=True):
        item = projection(run)
        from .artifacts import thumbnail_data
        for sample in item["samples"]:
            sample["thumbnail"] = thumbnail_data(store.path.parent / "artifacts" / run["run_id"] / f"{sample['sha256']}.png") if sample["sha256"] else None
        # Keep failed attempts as evidence, including oversized artifacts as metadata.
        for sample in item["samples"]:
            if sample["html"] and len(sample["html"].encode("utf-8")) > 120_000:
                sample["html"] = None
        # Images must not evict a run or its HTML. Drop the largest optional
        # images first, then exceptionally large HTML as metadata if necessary.
        for field in ("thumbnail", "html"):
            for sample in sorted(item["samples"], key=lambda s: len(s[field] or ""), reverse=True):
                if len(json.dumps(item, ensure_ascii=False).encode("utf-8")) <= MAX_SITE_RUN_BYTES:
                    break
                sample[field] = None
        payload["runs"].append(item)
    return payload
