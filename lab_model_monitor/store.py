from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import STATE


class RunStore:
    """One local owner for original runs, incremental samples and delivery state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STATE / "monitor.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, ended_at TEXT,
                status TEXT NOT NULL, contract_json TEXT NOT NULL,
                samples_json TEXT NOT NULL, result_json TEXT NOT NULL,
                origin TEXT NOT NULL, schedule_day TEXT UNIQUE,
                feishu_status TEXT NOT NULL DEFAULT 'pending',
                delivery_json TEXT NOT NULL DEFAULT '{}');
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in ("contract", "samples", "result", "delivery"):
            result[field] = json.loads(result.pop(field + "_json"))
        return result

    def start(self, contract: dict[str, Any], *, schedule_day: str | None = None,
              method: dict[str, Any] | None = None, notify: bool = True) -> str:
        identity = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO runs(run_id,created_at,status,contract_json,samples_json,result_json,origin,schedule_day) VALUES(?,?,'running',?,'[]',?,?,?)",
                       (identity, datetime.now(UTC).isoformat(), json.dumps(contract, ensure_ascii=False),
                        json.dumps({"method": method}, ensure_ascii=False) if method is not None else "{}",
                        "scheduled" if schedule_day else "manual", schedule_day))
            if not notify:
                db.execute("UPDATE runs SET feishu_status='skipped' WHERE run_id=?", (identity,))
        return identity

    def save_samples(self, run_id: str, samples: list[dict[str, Any]]) -> None:
        with self.connect() as db:
            db.execute("UPDATE runs SET samples_json=? WHERE run_id=? AND status='running'",
                       (json.dumps(samples, ensure_ascii=False, allow_nan=False), run_id))

    def finish(self, run_id: str, result: dict[str, Any], *, status: str | None = None) -> None:
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?,ended_at=?,samples_json=?,result_json=? WHERE run_id=? AND status='running'",
                       (status or ("success" if result["success"] else "failed"), datetime.now(UTC).isoformat(),
                        json.dumps(result.get("samples", []), ensure_ascii=False, allow_nan=False),
                        json.dumps(result, ensure_ascii=False, allow_nan=False), run_id))

    def import_run(self, run: dict[str, Any]) -> bool:
        """Idempotent legacy import; delivered history is never queued again."""
        with self.connect() as db:
            previous = db.execute("SELECT * FROM runs WHERE run_id=?", (run["run_id"],)).fetchone()
            if previous:
                saved = self.decode(previous)
                if any(saved[key] != run[key] for key in ("created_at", "ended_at", "status", "contract", "samples", "result")):
                    raise ValueError("Existing run differs from the imported historical record.")
                return False
            db.execute("INSERT INTO runs(run_id,created_at,ended_at,status,contract_json,samples_json,result_json,origin,feishu_status) VALUES(?,?,?,?,?,?,?,'imported','skipped')",
                       (run["run_id"], run["created_at"], run["ended_at"], run["status"],
                        json.dumps(run["contract"], ensure_ascii=False), json.dumps(run["samples"], ensure_ascii=False),
                        json.dumps(run["result"], ensure_ascii=False)))
        return True

    def get(self, run_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("Monitor run does not exist.")
        return self.decode(row)

    def for_day(self, day: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE schedule_day=?", (day,)).fetchone()
        return self.decode(row) if row else None

    def recent(self, *, days: int = 90, limit: int = 121, now: datetime | None = None,
               prompt_version: str | None = None) -> list[dict[str, Any]]:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
        with self.connect() as db:
            condition = " AND json_extract(contract_json, '$.prompt_version')=?" if prompt_version else ""
            parameters = [cutoff.isoformat(), *([prompt_version] if prompt_version else []), limit]
            rows = db.execute("SELECT * FROM runs WHERE created_at>=?" + condition + " ORDER BY created_at DESC LIMIT ?",
                              parameters).fetchall()
        return [self.decode(row) for row in rows]

    def pending_deliveries(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs WHERE feishu_status='pending' AND status!='running' ORDER BY created_at LIMIT 30").fetchall()
        return [self.decode(row) for row in rows]

    def delivery(self, run_id: str, channel: str, result: dict[str, Any]) -> None:
        with self.connect() as db:
            row = db.execute("SELECT delivery_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            payload = json.loads(row[0])
            payload[channel] = {**result, "updated_at": datetime.now(UTC).isoformat()}
            db.execute("UPDATE runs SET delivery_json=? WHERE run_id=?", (json.dumps(payload), run_id))
            if channel == "feishu" and result.get("success"):
                db.execute("UPDATE runs SET feishu_status='delivered' WHERE run_id=?", (run_id,))
