"""A bounded display projection of candy diagnostics; RunStore owns the results."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .store import RunStore
from .config import default_test, load_settings, load_credentials, validate_test

MAX_RUNS = 120
MAX_BODY_BYTES = 32 * 1024 * 1024
SAMPLE_STATUSES = {"passed", "wrong_answer", "format_error", "timeout", "api_error", "incomplete"}
PUBLIC_CONTRACT_FIELDS = (
    "prompt_version", "prompt_sha256", "expected_answer", "api_mode", "reasoning_effort",
    "max_output_tokens", "timeout_seconds", "web_search", "stream_failure_retry", "stream",
)


def validate_site_url(value: str) -> str:
    """Accept only an HTTPS origin; credentials never follow redirects."""
    value = value.strip().rstrip("/")
    if not value:
        return ""
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.path or parts.query or parts.fragment or parts.port not in {None, 443}):
        raise ValueError("AI monitor Site URL must be an HTTPS origin.")
    return value


def build_reasoning_site_snapshot(
    *, store: RunStore, schedule: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    """Export only fixed-puzzle data, omitting endpoints, account data and raw errors."""
    from .monitor import CANDY_INSTRUCTIONS, CANDY_PROMPT, CANDY_PROMPT_VERSION, CANDY_PROMPT_SHA256

    timestamp = now or datetime.now(UTC)
    runs = []
    tasks = store.recent(limit=MAX_RUNS + 1, days=90, now=timestamp, prompt_version=CANDY_PROMPT_VERSION)
    for task in tasks:
        if task['status'] not in {'success', 'failed', 'cancelled'}:
            continue
        contract = task['contract']
        if not isinstance(contract, dict) or not contract.get('prompt_sha256'):
            continue
        if (contract.get("prompt_version") != CANDY_PROMPT_VERSION
                or contract.get("prompt_sha256") != CANDY_PROMPT_SHA256
                or contract.get("expected_answer") != 21):
            continue
        contract_id = hashlib.sha256(json.dumps(
            contract, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        samples = []
        for sample in task["samples"] or []:
            if sample.get("status") not in SAMPLE_STATUSES:
                raise ValueError("Unsupported reasoning sample status.")
            error = str(sample.get("error") or "")
            http = re.search(r"HTTP(?:Error)?\s*[: ]?\s*([45]\d\d)\b", error, re.IGNORECASE)
            samples.append({
                "requested_model": sample["requested_model"],
                "returned_model": str(sample.get("returned_model") or "")[:200],
                "attempt": sample["attempt"], "requested_at": sample["requested_at"],
                "status": sample["status"], "answer": sample.get("answer"),
                "elapsed_seconds": sample["elapsed_seconds"],
                "response_text": str(sample.get("response_text") or "")[:1600],
                "response_truncated": len(str(sample.get("response_text") or "")) > 1600,
                "total_tokens": sample.get("total_tokens"),
                "http_status": int(http.group(1)) if http else None,
            })
        runs.append({
            "run_id": task["run_id"], "created_at": task["created_at"],
            "ended_at": task["ended_at"],
            "status": task["status"], "contract_id": contract_id,
            "contract": {key: contract[key] for key in PUBLIC_CONTRACT_FIELDS if key in contract},
            "samples": samples,
        })
    payload = {
        "schema_version": 1, "synced_at": timestamp.isoformat(),
        "schedule": {key: schedule[key] for key in (
            "enabled", "daily_time", "models", "attempts_per_model"
        )},
        "timezone": "Asia/Taipei", "retention_days": 90,
        "history_limited": len(runs) > MAX_RUNS,
        "method": {"instructions": CANDY_INSTRUCTIONS, "prompt": CANDY_PROMPT},
        "runs": runs[:MAX_RUNS],
    }
    payload["schedule"]["daily_times"] = schedule.get("daily_times", [])
    return payload


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def sync_reasoning_site(
    *, settings: dict[str, Any] | None = None, credentials: dict[str, str] | None = None,
    store: RunStore | None = None,
) -> dict[str, Any]:
    """Push stored results once without issuing model requests."""
    settings = settings or load_settings()
    credentials = credentials or load_credentials()
    if validate_test(settings.get("test")) != default_test():
        return {"success": True, "status": "custom_test_local_only"}
    try:
        site_url = validate_site_url(settings["site_url"])
        if not site_url:
            return {"success": True, "status": "disabled"}
        token = credentials.get("site_token")
        if not token:
            return {"success": False, "status": "missing_site_credential"}
        snapshot = build_reasoning_site_snapshot(
            store=store or RunStore(), schedule=settings["schedule"]
        )
        from .animation import site_snapshot, VERSION, MAX_SITE_RUNS
        from .artifacts import prepare_run
        artifact_store = store or RunStore()
        for run in artifact_store.recent(prompt_version=VERSION, limit=MAX_SITE_RUNS, completed_only=True):
            prepare_run(artifact_store, run["run_id"])
        animation_snapshot = site_snapshot(artifact_store)
        for payload in (snapshot, animation_snapshot):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(body) > MAX_BODY_BYTES:
                return {"success": False, "status": "snapshot_too_large"}
            request = Request(site_url + "/api/sync", data=body, method="POST", headers={
                "Content-Type": "application/json", "User-Agent": "LabModelMonitor/0.1.0",
                "Authorization": f"Bearer {token}", "OAI-Sites-Authorization": f"Bearer {token}",
            })
            with build_opener(_NoRedirect()).open(request, timeout=30) as response:
                result = json.loads(response.read(8192).decode("utf-8"))
            if not isinstance(result, dict) or result.get("success") is not True:
                return {"success": False, "status": "invalid_site_response"}
        return {"success": True, "status": "synced", "runs": len(snapshot["runs"]),
                "animation_runs": len(animation_snapshot["runs"])}
    except HTTPError as exc:
        return {"success": False, "status": "http_error", "http_status": exc.code}
    except (URLError, OSError, ValueError, KeyError, TypeError):
        return {"success": False, "status": "sync_failed"}
