"""Outbound Feishu reporting and Site sync, separate from model evaluation."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib.request import Request, build_opener
from uuid import NAMESPACE_URL, uuid5

from .site import _NoRedirect, sync_reasoning_site
from .store import RunStore


def _post(url: str, payload: dict[str, Any], token: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": "LabModelMonitor/0.1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers, method="POST")
    with build_opener(_NoRedirect()).open(request, timeout=30) as response:
        result = json.loads(response.read(1024 * 1024))
    if not isinstance(result, dict):
        raise ValueError("Invalid Feishu response.")
    return result


def send_feishu(run: dict[str, Any], credentials: dict[str, str], *, site_url: str = "",
                requester: Callable[..., dict[str, Any]] = _post) -> dict[str, Any]:
    if not all(credentials.get(key) for key in ("feishu_app_id", "feishu_app_secret", "feishu_chat_id")):
        return {"success": False, "status": "missing_feishu_credential"}
    try:
        auth = requester("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
            "app_id": credentials["feishu_app_id"], "app_secret": credentials["feishu_app_secret"]})
        if auth.get("code") != 0 or not auth.get("tenant_access_token"):
            return {"success": False, "status": "feishu_auth_failed", "code": auth.get("code")}
        summary = str(run["result"].get("notification_summary") or "检测结果暂不可用。")
        canonical = run["result"].get("contract", {}).get("prompt_version", "candy-shape-selection-v1") == "candy-shape-selection-v1"
        if site_url and canonical:
            summary += "\n\n[查看详细结果](" + site_url + ")"
        title = "实验室模型监测 · 糖果测试" if canonical else "实验室模型监测 · 自定义测试"
        card = {"config": {"wide_screen_mode": True}, "header": {"title": {"tag": "plain_text", "content": title},
                "template": "green" if run["status"] == "success" else "orange"},
                "elements": [{"tag": "markdown", "content": summary}]}
        result = requester("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id", {
            "receive_id": credentials["feishu_chat_id"], "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
            "uuid": str(uuid5(NAMESPACE_URL, "lab-model-monitor:" + run["run_id"]))}, auth["tenant_access_token"])
        if result.get("code") != 0:
            return {"success": False, "status": "feishu_send_failed", "code": result.get("code")}
        return {"success": True, "status": "delivered"}
    except Exception:
        return {"success": False, "status": "feishu_transport_failed"}


def deliver(*, store: RunStore, settings: dict[str, Any], credentials: dict[str, str],
            run_id: str | None = None, sender: Callable[..., dict[str, Any]] = send_feishu,
            syncer: Callable[..., dict[str, Any]] = sync_reasoning_site) -> dict[str, Any]:
    try:
        site = syncer(store=store, settings=settings, credentials=credentials)
    except Exception:
        site = {"success": False, "status": "sync_failed"}
    if run_id:
        store.delivery(run_id, "site", site)
    notifications = []
    if settings["feishu_enabled"]:
        for run in store.pending_deliveries():
            result = sender(run, credentials, site_url=settings["site_url"])
            store.delivery(run["run_id"], "feishu", result)
            notifications.append({"run_id": run["run_id"], **result})
    return {"success": site["success"] and all(item["success"] for item in notifications),
            "site": site, "feishu": notifications}
