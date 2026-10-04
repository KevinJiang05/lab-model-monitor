"""Local control operations over the existing config, CLI, scheduler and RunStore."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import uuid4

from . import config
from .client import GPTAPIError, GPTClientConfig, OpenAICompatibleClient
from .monitor import CANDY_PROMPT_SHA256, execution_lock
from .store import RunStore


class BusyError(RuntimeError):
    pass


@contextmanager
def job_guard():
    lock = execution_lock(config.STATE / "job.lock")
    try:
        lock.__enter__()
    except OSError as exc:
        if exc.errno not in {11, 13, 35}:
            raise
        raise BusyError("Detection or delivery is already running.") from exc
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


class WindowsScheduler:
    def invoke(self, action: str) -> dict[str, Any]:
        if os.name != "nt":
            return {"state": "unsupported", "task_name": "LabModelMonitor-Daily"}
        result = subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(config.ROOT / "scripts" / "schedule.ps1"), "-Action", action,
        ], cwd=config.ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=45,
           creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError("Windows schedule update failed.")
        return json.loads(result.stdout.lstrip("\ufeff"))

    def status(self) -> dict[str, Any]:
        return self.invoke("Status")

    def apply(self, settings: dict[str, Any]) -> dict[str, Any]:
        return self.invoke("Install" if settings["schedule"]["enabled"] else "Disable")


def public_run(run: dict[str, Any], *, detailed: bool = False) -> dict[str, Any]:
    result = {key: run[key] for key in ("run_id", "created_at", "ended_at", "status", "origin", "delivery")}
    result["contract"] = {key: value for key, value in run["contract"].items() if key != "base_url"}
    models = []
    for model in dict.fromkeys(sample["requested_model"] for sample in run["samples"]):
        samples = [sample for sample in run["samples"] if sample["requested_model"] == model]
        completed = sum(sample["status"] in {"passed", "wrong_answer", "format_error", "generated"} for sample in samples)
        models.append({"model": model, "attempts": len(samples), "completed": completed,
                       "passed": sum(sample["status"] == "passed" for sample in samples),
                       "generated": sum(sample["status"] == "generated" for sample in samples),
                       "errors": sum(sample["status"] in {"api_error", "timeout", "incomplete"} for sample in samples),
                       "in_progress": sum(sample["status"] == "running" for sample in samples),
                       "received_characters": sum(len(sample.get("response_text", "")) for sample in samples),
                       "total_tokens": sum(sample.get("total_tokens") or 0 for sample in samples),
                       "usage_complete": all(sample.get("total_tokens") is not None for sample in samples)})
    result["models"] = models
    result["sample_count"] = len(run["samples"])
    if detailed:
        method = run["result"].get("method")
        if method is None and run["contract"].get("prompt_sha256") == CANDY_PROMPT_SHA256:
            method = config.default_test()
        result["method"] = method
        result["samples"] = []
        for sample in run["samples"]:
            item = {key: sample.get(key) for key in (
                "requested_model", "returned_model", "attempt", "requested_at", "status", "answer",
                "elapsed_seconds", "response_text", "total_tokens", "completion_status", "last_event_at", "last_event", "stream_event_count")}
            http = re.search(r"HTTP(?:Error)?\s*[: ]?\s*([45]\d\d)\b", str(sample.get("error") or ""), re.I)
            item["http_status"] = int(http.group(1)) if http else None
            result["samples"].append(item)
    return result


class ControlService:
    def __init__(self, *, scheduler: Any = None, store: RunStore | None = None) -> None:
        self.scheduler = scheduler or WindowsScheduler()
        self.store = store or RunStore()
        self.guard = threading.RLock()
        self.scheduler_guard = threading.Lock()
        self.schedule_cache: tuple[float, dict[str, Any]] | None = None
        self.job: dict[str, Any] = {"state": "idle"}

    def schedule_status(self, *, refresh: bool = False) -> dict[str, Any]:
        with self.scheduler_guard:
            if refresh or not self.schedule_cache or monotonic() - self.schedule_cache[0] > 10:
                try:
                    result = self.scheduler.status()
                except Exception:
                    result = {"state": "unavailable", "task_name": "LabModelMonitor-Daily"}
                self.schedule_cache = (monotonic(), result)
            return self.schedule_cache[1]

    def snapshot(self) -> dict[str, Any]:
        with self.guard:
            settings = config.load_settings()
            credentials = config.credential_details()
            job = dict(self.job)
        busy = job["state"] == "running"
        if not busy:
            try:
                with job_guard():
                    pass
            except BusyError:
                busy = True
        return {"success": True, "settings": settings, "credentials": credentials,
                "scheduler": self.schedule_status(), "job": job, "busy": busy,
                "standard_test": settings["test"] == config.default_test(),
                "default_test": config.default_test(),
                "runs": [public_run(run) for run in self.store.recent(limit=20)]}

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = config.validate_settings(payload["settings"])
        updates = payload.get("credentials") or {}
        clear = payload.get("clear_credentials") or []
        if not isinstance(updates, dict) or not isinstance(clear, list):
            raise ValueError("Invalid credential update.")
        with self.guard:
            if self.job["state"] == "running":
                raise BusyError("A control operation is running.")
            with job_guard():
                previous = config.load_settings()
                settings_path = config.STATE / "settings.json"
                credential_path = config.STATE / "credentials.json"
                previous_file = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else None
                # Private rollback stays in memory and never leaves this owner.
                previous_credentials = json.loads(credential_path.read_text(encoding="utf-8")) if credential_path.exists() else None
                schedule_changed = any(settings["schedule"][key] != previous["schedule"][key] for key in ("enabled", "daily_time"))
                status = self.schedule_status(refresh=True)
                reconcile = (settings["schedule"]["enabled"] and status["state"] in {"not_installed", "Disabled"}
                             or not settings["schedule"]["enabled"] and status["state"] in {"Ready", "Running"})
                applied = False
                wrote_settings = False
                wrote_credentials = False
                try:
                    if updates or clear:
                        config.update_credentials(updates, clear)
                        wrote_credentials = True
                    if settings["schedule"]["enabled"] and not config.configuration_readiness(settings):
                        raise ValueError("Enabled detection requires the model key and credentials for enabled delivery channels.")
                    config.write_json(settings_path, settings)
                    wrote_settings = True
                    if schedule_changed or reconcile:
                        applied = True
                        self.scheduler.apply(settings)
                except Exception:
                    if wrote_settings:
                        if previous_file is not None:
                            config.write_json(settings_path, previous_file)
                        else:
                            settings_path.unlink(missing_ok=True)
                    if wrote_credentials:
                        if previous_credentials is not None:
                            config.write_json(credential_path, previous_credentials)
                        else:
                            credential_path.unlink(missing_ok=True)
                    if applied:
                        self.scheduler.apply(previous)
                    self.schedule_cache = None
                    raise
                self.schedule_cache = None
        return self.snapshot()

    def start(self, action: str) -> dict[str, Any]:
        if action not in {"run", "sync", "models"}:
            raise ValueError("Unknown control action.")
        with self.guard:
            if self.job["state"] == "running":
                raise BusyError("A control operation is running.")
            with job_guard():
                pass
            if action == "run" and not config.credential_status()["api"]:
                raise ValueError("Model API key is not configured.")
            identity = str(uuid4())
            self.job = {"id": identity, "action": action, "state": "running", "started_at": datetime.now(UTC).isoformat()}
            threading.Thread(target=self._worker, args=(identity, action), daemon=True).start()
            return dict(self.job)

    def _worker(self, identity: str, action: str) -> None:
        try:
            if action == "models":
                with execution_lock(config.STATE / "job.lock"):
                    settings = config.load_settings()
                    client = OpenAICompatibleClient(api_key=config.load_credentials()["api_key"],
                        config=GPTClientConfig.from_mapping(settings["api"]), retry_stream_failures=False)
                    result = {"success": True, "models": client.list_models()}
            else:
                result = self._cli(action)
            state = "success" if result.get("success") else "failed"
        except GPTAPIError as exc:
            http = re.search(r"HTTP\s+(\d{3})", str(exc))
            result = {"success": False, "status": "api_error", "http_status": int(http.group(1)) if http else None}
            state = "failed"
        except Exception as exc:
            result = {"success": False, "status": "operation_failed", "error_type": type(exc).__name__}
            state = "failed"
        with self.guard:
            if self.job.get("id") == identity:
                self.job.update(state=state, result=result, ended_at=datetime.now(UTC).isoformat())

    @staticmethod
    def _cli(action: str) -> dict[str, Any]:
        result = subprocess.run([sys.executable, "-X", "utf8", "-m", "lab_model_monitor", action],
            cwd=config.ROOT, capture_output=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return json.loads(result.stdout)
