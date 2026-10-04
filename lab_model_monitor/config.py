from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "runtime"
CREDENTIAL_ENVS = {"api_key": "OPENAI_API_KEY", "site_token": "MONITOR_SITE_TOKEN",
                   "feishu_app_id": "FEISHU_APP_ID", "feishu_app_secret": "FEISHU_APP_SECRET",
                   "feishu_chat_id": "FEISHU_CHAT_ID"}


def default_test() -> dict[str, Any]:
    from .monitor import CANDY_EXPECTED_ANSWER, CANDY_INSTRUCTIONS, CANDY_PROMPT

    return {"instructions": CANDY_INSTRUCTIONS, "prompt": CANDY_PROMPT,
            "expected_answer": CANDY_EXPECTED_ANSWER}


def validate_test(value: dict[str, Any] | None) -> dict[str, Any]:
    values = {**default_test(), **(value or {})}
    for field, limit in (("instructions", 2000), ("prompt", 10000)):
        if not isinstance(values[field], str) or not values[field].strip() or len(values[field]) > limit:
            raise ValueError(f"{field} must be non-empty text of at most {limit} characters.")
    answer = values["expected_answer"]
    if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer <= 999999:
        raise ValueError("Expected answer must be an integer from 0 to 999999.")
    return {"instructions": values["instructions"].strip(), "prompt": values["prompt"].strip(),
            "expected_answer": answer}


def validate_settings(raw: dict[str, Any]) -> dict[str, Any]:
    from .client import GPTClientConfig
    from .schedule import AIReasoningSchedule
    from .site import validate_site_url

    if not isinstance(raw, dict):
        raise ValueError("Settings must be an object.")
    schedule = AIReasoningSchedule.from_mapping(raw.get("schedule")).to_dict()
    api = GPTClientConfig.from_mapping(raw.get("api")).to_dict(enabled=True)
    if raw.get("timezone", "Asia/Taipei") != "Asia/Taipei":
        raise ValueError("The daily schedule uses Asia/Taipei.")
    if not isinstance(raw.get("feishu_enabled", True), bool):
        raise ValueError("Feishu enabled must be a boolean.")
    return {"api": api, "schedule": schedule, "timezone": "Asia/Taipei",
            "site_url": validate_site_url(str(raw.get("site_url") or "")),
            "feishu_enabled": raw.get("feishu_enabled", True), "test": validate_test(raw.get("test"))}


def load_settings(path: Path | None = None) -> dict[str, Any]:
    settings_path = path or STATE / "settings.json"
    raw = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    return validate_settings(raw)


def load_credentials() -> dict[str, str]:
    """Private local configuration; callers must never log or return values."""
    path = STATE / "credentials.json"
    values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for field, variable in CREDENTIAL_ENVS.items():
        if os.environ.get(variable):
            values[field] = os.environ[variable]
    return {field: str(values.get(field) or "").strip() for field in (
        "api_key", "site_token", "feishu_app_id", "feishu_app_secret", "feishu_chat_id")}


def credential_status() -> dict[str, bool]:
    values = load_credentials()
    return {"api": bool(values["api_key"]), "site": bool(values["site_token"]),
            "feishu": all(values[key] for key in (
                "feishu_app_id", "feishu_app_secret", "feishu_chat_id"))}


def credential_details() -> dict[str, dict[str, Any]]:
    values = load_credentials()
    return {field: {"configured": bool(values[field]),
                    "source": "environment" if os.environ.get(variable) else "local" if values[field] else "missing"}
            for field, variable in CREDENTIAL_ENVS.items()}


def configuration_readiness(settings: dict[str, Any]) -> bool:
    status = credential_status()
    return (status["api"] and (not settings["feishu_enabled"] or status["feishu"])
            and (not settings["site_url"] or settings.get("test", default_test()) != default_test() or status["site"]))


def update_credentials(updates: dict[str, str], clear: list[str] | None = None) -> None:
    """Blank values preserve local fields; no existing values leave this owner."""
    clear = clear or []
    if set(updates) - CREDENTIAL_ENVS.keys() or set(clear) - CREDENTIAL_ENVS.keys():
        raise ValueError("Unknown credential field.")
    if any(not isinstance(value, str) or len(value) > 8192 for value in updates.values()):
        raise ValueError("Credential fields must be text of at most 8192 characters.")
    path = STATE / "credentials.json"
    values = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for field in clear:
        values.pop(field, None)
    for field, value in updates.items():
        if value.strip():
            values[field] = value.strip()
    write_json(path, values)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
