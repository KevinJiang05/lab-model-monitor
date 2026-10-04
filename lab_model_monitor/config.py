from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "runtime"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    from .client import GPTClientConfig
    from .schedule import AIReasoningSchedule
    from .site import validate_site_url

    raw = json.loads((path or STATE / "settings.json").read_text(encoding="utf-8"))
    schedule = AIReasoningSchedule.from_mapping(raw.get("schedule")).to_dict()
    api = GPTClientConfig.from_mapping(raw.get("api")).to_dict(enabled=True)
    if raw.get("timezone", "Asia/Taipei") != "Asia/Taipei":
        raise ValueError("The daily schedule uses Asia/Taipei.")
    return {"api": api, "schedule": schedule, "timezone": "Asia/Taipei",
            "site_url": validate_site_url(str(raw.get("site_url") or "")),
            "feishu_enabled": bool(raw.get("feishu_enabled", True))}


def load_credentials() -> dict[str, str]:
    """Private local configuration; callers must never log or return values."""
    path = STATE / "credentials.json"
    values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for field, variable in {"api_key": "OPENAI_API_KEY", "site_token": "MONITOR_SITE_TOKEN",
                            "feishu_app_id": "FEISHU_APP_ID", "feishu_app_secret": "FEISHU_APP_SECRET",
                            "feishu_chat_id": "FEISHU_CHAT_ID"}.items():
        if os.environ.get(variable):
            values[field] = os.environ[variable]
    return {field: str(values.get(field) or "").strip() for field in (
        "api_key", "site_token", "feishu_app_id", "feishu_app_secret", "feishu_chat_id")}


def credential_status() -> dict[str, bool]:
    values = load_credentials()
    return {"api": bool(values["api_key"]), "site": bool(values["site_token"]),
            "feishu": all(values[key] for key in (
                "feishu_app_id", "feishu_app_secret", "feishu_chat_id"))}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
