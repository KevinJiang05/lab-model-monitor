from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor

from .config import configuration_readiness, credential_status, load_credentials, load_settings
from .delivery import deliver
from .monitor import execution_lock, run_monitor
from .config import STATE
from .store import RunStore


def main() -> int:
    parser = argparse.ArgumentParser(description="实验室模型监测")
    parser.add_argument("command", choices=("run", "run-all", "scheduled-run", "sync", "status", "console", "animation"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "console":
            from .console import serve
            serve(port=args.port)
            return 0
        store = RunStore()
        if args.command == "status":
            settings = load_settings()
            latest = store.recent(limit=1)
            result = {"success": True, "schedule": settings["schedule"], "credentials": credential_status(),
                      "ready": configuration_readiness(settings),
                      "latest": {key: latest[0][key] for key in ("run_id", "created_at", "status", "origin")} if latest else None}
        else:
            # Capture configuration after acquiring the same lock as console saves.
            with execution_lock(STATE / "job.lock"):
                settings = load_settings()
                credentials = load_credentials()
                if args.command == "sync":
                    result = deliver(store=store, settings=settings, credentials=credentials)
                else:
                    slot_time = datetime.now(UTC)
                    if args.command in {"scheduled-run", "run-all"}:
                        # One model request per lane; both lanes share the outer job lock.
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            futures = [pool.submit(run_monitor, settings=settings, store=store,
                                credentials=credentials, now=slot_time,
                                scheduled=args.command == "scheduled-run", animation_test=animation,
                                animation_attempts=3, lock_path=STATE / ("animation.lock" if animation else "candy.lock"))
                                for animation in (False, True)]
                            outcomes = []
                            for future in futures:
                                try:
                                    outcomes.append(future.result())
                                except Exception as exc:
                                    outcomes.append({"success": False, "status": "operation_failed", "error_type": type(exc).__name__})
                        result, animation_result = outcomes
                        result["animation"] = animation_result
                        result["success"] = result["success"] and animation_result["success"]
                    else:
                        result = run_monitor(settings=settings, store=store, credentials=credentials,
                                             now=slot_time, animation_test=args.command == "animation")
                    animation_run = result if args.command == "animation" else result.get("animation", {})
                    if animation_run.get("run_id"):
                        from .artifacts import prepare_run
                        animation_run["artifacts"] = prepare_run(store, animation_run["run_id"])
                    if args.command == "animation":
                        from .site import sync_reasoning_site
                        result["site"] = sync_reasoning_site(store=store, settings=settings, credentials=credentials)
                    if args.command != "animation" and result["status"] not in {"disabled", "not_due"}:
                        result["delivery"] = deliver(store=store, settings=settings, credentials=credentials,
                                                      run_id=result.get("run_id"))
                        result["success"] = result["success"] and result["delivery"]["success"]
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["success"] else 1
    except Exception as exc:
        print(json.dumps({"success": False, "status": "operation_failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
