"""Fixed candy contract, honest grading and independently persisted executions."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator

from .client import GPTAPIError, GPTClientConfig, JsonRequester, OpenAICompatibleClient
from .config import STATE, load_credentials, load_settings
from .schedule import AIReasoningSchedule
from .store import RunStore

TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")

CANDY_PROMPT_VERSION = "candy-shape-selection-v1"
CANDY_EXPECTED_ANSWER = 21
CANDY_INSTRUCTIONS = "独立解答数学问题，不允许联网或调用工具。"
CANDY_PROMPT = """在一个黑色袋子里放有三种口味的糖果，每种糖果有两种形状。
不同形状靠手感可以分辨，口味无法在取出前分辨。数量如下：

| 形状 | 苹果味 | 桃子味 | 西瓜味 |
| 圆形 | 7 | 9 | 8 |
| 五角星形 | 7 | 6 | 4 |

参赛者须在活动前决定取出糖果的总数，可以凭手感选择取出某种形状的糖果，
但不能根据口味挑选，取出的糖果不放回。
最少取出多少个，才能保证手中同时拥有“圆形苹果味与五角星桃子味”，
或者“圆形桃子味与五角星苹果味”中的至少一组？

最终回答第一行只写一个纯阿拉伯整数，不带单位、标点或解释。
第二行起可以写简短推理和最小性的证明。"""
CANDY_PROMPT_SHA256 = hashlib.sha256(
    (CANDY_INSTRUCTIONS + "\n" + CANDY_PROMPT).encode("utf-8")
).hexdigest()

def grade_candy_answer(text: str) -> tuple[str, int | None]:
    """Grade only the first line; explanatory occurrences never imply success."""
    lines = text.splitlines()
    if not lines or re.fullmatch(r"[0-9]{1,6}", lines[0]) is None:
        return "format_error", None
    answer = int(lines[0])
    return ("passed" if answer == CANDY_EXPECTED_ANSWER else "wrong_answer"), answer


def _contract(settings: dict[str, Any], schedule: AIReasoningSchedule) -> dict[str, Any]:
    return {
        "prompt_version": CANDY_PROMPT_VERSION,
        "prompt_sha256": CANDY_PROMPT_SHA256,
        "expected_answer": CANDY_EXPECTED_ANSWER,
        "base_url": settings["base_url"],
        "api_mode": settings["api_mode"],
        "reasoning_effort": schedule.reasoning_effort,
        "max_output_tokens": schedule.max_output_tokens,
        "timeout_seconds": schedule.timeout_seconds,
        "web_search": False,
        "stream_failure_retry": False,
    }



def monitor_notification_summary(result: dict[str, Any]) -> str:
    """Controlled, bounded daily content for the existing generic Feishu card."""
    lines = [f"糖果题 · {result.get('contract', {}).get('reasoning_effort', '-')} · 正确答案 21"]
    for model in result.get("models") or []:
        lines.append(
            f"{model['model']}：{model['passed']}/{model['attempts']}；"
            f"答错 {model['wrong_answer']}，格式 {model['format_error']}，"
            f"接口/超时/截断 {model['api_error'] + model['timeout'] + model['incomplete']}；"
            f"近7天有效回答 {model['seven_day_passed']}/{model['seven_day_completed']}"
        )
    lines.append("通过仅代表本题表现，不认证模型身份。")
    return "\n".join(lines)[:240]





@contextmanager
def execution_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def summarize(samples: list[dict[str, Any]], contract: dict[str, Any], store: RunStore) -> list[dict[str, Any]]:
    recent = [sample for run in store.recent(days=7, limit=500)
              if run["status"] != "running" and run["contract"] == contract for sample in run["samples"]]
    summaries = []
    for model in dict.fromkeys(sample["requested_model"] for sample in samples):
        current = [sample for sample in samples if sample["requested_model"] == model]
        window = [sample for sample in recent + samples if sample["requested_model"] == model]
        counts = {status: sum(sample["status"] == status for sample in current) for status in (
            "passed", "wrong_answer", "format_error", "timeout", "api_error", "incomplete")}
        summaries.append({"model": model, "attempts": len(current), **counts,
                          "elapsed_seconds": round(sum(sample["elapsed_seconds"] for sample in current), 2),
                          "total_tokens": sum(sample["total_tokens"] or 0 for sample in current),
                          "usage_complete": all(sample["total_tokens"] is not None for sample in current),
                          "seven_day_passed": sum(sample["status"] == "passed" for sample in window),
                          "seven_day_attempts": len(window),
                          "seven_day_completed": sum(sample["status"] in {"passed", "wrong_answer", "format_error"} for sample in window)})
    return summaries


def run_monitor(*, settings: dict[str, Any] | None = None, credentials: dict[str, str] | None = None,
                store: RunStore | None = None, requester: JsonRequester | None = None,
                scheduled: bool = False, lock_path: Path | None = None,
                now: datetime | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    schedule = AIReasoningSchedule.from_mapping(settings["schedule"])
    timestamp = (now or datetime.now(UTC)).astimezone(TAIPEI)
    if scheduled and not schedule.enabled:
        return {"success": True, "status": "disabled"}
    if scheduled and timestamp.strftime("%H:%M") < schedule.daily_time:
        return {"success": True, "status": "not_due"}
    credentials = credentials or load_credentials()
    if not credentials.get("api_key"):
        raise ValueError("Model API credential is missing; no requests were issued.")
    store = store or RunStore()
    contract = _contract(settings["api"], schedule)
    with execution_lock(lock_path or STATE / "monitor.lock"):
        # An OS lock has no surviving owner after a crash. Keep partial evidence.
        for previous in store.recent(limit=500):
            if previous["status"] == "running":
                result = {"success": False, "contract": previous["contract"], "samples": previous["samples"],
                          "models": [], "notification_summary": "糖果检测进程中断；已完成样本保留，本轮未自动补测。"}
                store.finish(previous["run_id"], result)
        day = timestamp.date().isoformat() if scheduled else None
        if day and (previous := store.for_day(day)):
            return {"success": previous["status"] == "success", "status": "already_run", "run_id": previous["run_id"]}
        try:
            identity = store.start(contract, schedule_day=day)
        except sqlite3.IntegrityError:
            return {"success": False, "status": "already_run"}
        samples: list[dict[str, Any]] = []
        try:
            for attempt in range(1, schedule.attempts_per_model + 1):
                for model in schedule.models:
                    started = perf_counter()
                    sample: dict[str, Any] = {
                        "requested_model": model, "attempt": attempt, "requested_at": datetime.now(UTC).isoformat(),
                        "returned_model": "", "response_id": "", "response_text": "", "answer": None,
                        "input_tokens": None, "output_tokens": None, "total_tokens": None,
                        "error": "", "completion_status": ""}
                    try:
                        client = OpenAICompatibleClient(api_key=credentials["api_key"],
                            config=GPTClientConfig.from_mapping({**settings["api"], "model": model,
                                                                "timeout_seconds": schedule.timeout_seconds}),
                            requester=requester, retry_stream_failures=False)
                        response = client.generate_text(instructions=CANDY_INSTRUCTIONS, input_text=CANDY_PROMPT,
                            reasoning_effort=schedule.reasoning_effort, max_output_tokens=schedule.max_output_tokens)
                        sample.update(returned_model=response.model, response_id=response.response_id,
                                      response_text=response.text, input_tokens=response.input_tokens,
                                      output_tokens=response.output_tokens, total_tokens=response.total_tokens,
                                      completion_status=response.completion_status)
                        if response.completion_status not in {"", "completed", "stop"}:
                            sample.update(status="incomplete", error=f"Response status: {response.completion_status}")
                        else:
                            sample["status"], sample["answer"] = grade_candy_answer(response.text)
                    except GPTAPIError as exc:
                        error = str(exc).replace(credentials["api_key"], "[redacted]")
                        status = "timeout" if "TimeoutError" in error else "api_error"
                        if "incomplete" in error:
                            status = "incomplete"
                        sample.update(status=status, error=error[:500])
                    except (TimeoutError, OSError, ValueError) as exc:
                        sample.update(status="timeout" if isinstance(exc, TimeoutError) else "api_error", error=type(exc).__name__)
                    sample["elapsed_seconds"] = round(perf_counter() - started, 3)
                    samples.append(sample)
                    store.save_samples(identity, samples)
            result = {"success": all(sample["status"] == "passed" for sample in samples),
                      "contract": contract, "samples": samples, "models": summarize(samples, contract, store)}
            result["notification_summary"] = monitor_notification_summary(result)
            store.finish(identity, result)
        except BaseException:
            store.finish(identity, {"success": False, "contract": contract, "samples": samples, "models": [],
                                   "notification_summary": "糖果检测进程中断；已完成样本保留，本轮未自动补测。"})
            raise
        return {"success": result["success"], "status": "success" if result["success"] else "failed", "run_id": identity,
                "models": result["models"]}
