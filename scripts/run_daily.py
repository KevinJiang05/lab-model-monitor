"""Hidden scheduled entrypoint; bounded, secret-free JSON logs."""

import contextlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from lab_model_monitor.__main__ import main

log = root / "runtime" / "logs" / "daily.log"
log.parent.mkdir(parents=True, exist_ok=True)
if log.exists() and log.stat().st_size > 5 * 1024 * 1024:
    for suffix in (2, 1):
        previous = log.with_suffix(f".log.{suffix}")
        if previous.exists():
            os.replace(previous, log.with_suffix(f".log.{suffix + 1}"))
    os.replace(log, log.with_suffix(".log.1"))
sys.argv = [sys.argv[0], "scheduled-run"]
with log.open("a", encoding="utf-8") as output, contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
    print(datetime.now(UTC).isoformat())
    code = main()
sys.exit(code)
