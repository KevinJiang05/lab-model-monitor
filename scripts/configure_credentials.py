"""Interactive hidden entry; never print credential values."""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lab_model_monitor.config import STATE, credential_status, write_json

values = {}
for field, label in (
    ("api_key", "Model API key"), ("site_token", "Site write token"),
    ("feishu_app_id", "Feishu App ID"), ("feishu_app_secret", "Feishu App Secret"),
    ("feishu_chat_id", "Feishu recipient Chat ID"),
):
    value = getpass.getpass(label + " (hidden): ").strip()
    if not value:
        raise SystemExit("All credential fields are required; configuration was not changed.")
    values[field] = value
write_json(STATE / "credentials.json", values)
print(credential_status())
