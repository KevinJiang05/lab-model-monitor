import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import ts from "typescript";

// Exercise production SQL with real SQLite. This adapter only provides the
// D1 transport methods, including batch transaction/rollback behavior.
class LocalD1 {
  database = new DatabaseSync(":memory:");
  constructor() {
    this.database.exec("CREATE TABLE monitor_snapshots (id TEXT PRIMARY KEY, payload TEXT NOT NULL, generated_at INTEGER NOT NULL)");
  }
  prepare(sql, values = []) {
    return {
      bind: (...args) => this.prepare(sql, args),
      all: async () => ({ results: this.database.prepare(sql).all(...values) }),
      run: async () => ({ meta: { changes: this.database.prepare(sql).run(...values).changes } }),
    };
  }
  async batch(statements) {
    this.database.exec("BEGIN");
    try {
      const results = [];
      for (const statement of statements) results.push(await statement.run());
      this.database.exec("COMMIT");
      return results;
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }
}

const source = readFileSync(new URL("../db/animation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { readAnimationSnapshot, writeAnimationSnapshot } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function snapshot(day, start = 0, count = 20) {
  return { kind: "animation", schema_version: 1, synced_at: `2026-10-${day}T00:00:00Z`,
    runs: Array.from({ length: count }, (_, n) => ({ run_id: `run-${start + n}`,
      created_at: `2026-10-05T00:${String(n).padStart(2, "0")}:00Z`,
      samples: [{ html: `<html><svg/></html><!--${"x".repeat(120000)}-->`, thumbnail: "x".repeat(200000) }] })) };
}

test("20 full animation rows round-trip above the D1 single-row limit", async () => {
  const db = new LocalD1();
  const value = snapshot("06");
  assert.ok(Buffer.byteLength(JSON.stringify(value)) > 2_000_000);
  assert.equal(await writeAnimationSnapshot(db, value), true);
  assert.deepEqual(await readAnimationSnapshot(db), value);
  const rows = db.database.prepare("SELECT length(CAST(payload AS BLOB)) AS bytes FROM monitor_snapshots").all();
  assert.equal(rows.length, 21);
  assert.ok(rows.every(row => row.bytes < 1_500_000));
  db.database.close();
});

test("legacy snapshot remains readable and converts on sync", async () => {
  const db = new LocalD1();
  const legacy = snapshot("05", 0, 2);
  await db.prepare("INSERT INTO monitor_snapshots VALUES ('animation', ?, ?)").bind(JSON.stringify(legacy), Date.parse(legacy.synced_at)).run();
  assert.deepEqual(await readAnimationSnapshot(db), legacy);
  const current = snapshot("06");
  await writeAnimationSnapshot(db, current);
  assert.deepEqual(await readAnimationSnapshot(db), current);
  db.database.close();
});

test("old deliveries cannot overwrite or prune recent history", async () => {
  const db = new LocalD1();
  const current = snapshot("07", 10);
  await writeAnimationSnapshot(db, current);
  assert.equal(await writeAnimationSnapshot(db, snapshot("06")), false);
  assert.deepEqual(await readAnimationSnapshot(db), current);
  assert.equal(db.database.prepare("SELECT count(*) AS total FROM monitor_snapshots").get().total, 21);
  db.database.close();
});

test("replacement prunes only expired display rows, including equal timestamp retries", async () => {
  const db = new LocalD1();
  await db.prepare("INSERT INTO monitor_snapshots VALUES ('main', '{}', 0)").run();
  await writeAnimationSnapshot(db, snapshot("06"));
  const next = snapshot("06", 20);
  await writeAnimationSnapshot(db, next);
  assert.deepEqual(await readAnimationSnapshot(db), next);
  assert.equal(db.database.prepare("SELECT count(*) AS total FROM monitor_snapshots").get().total, 22);
  assert.equal(db.database.prepare("SELECT payload FROM monitor_snapshots WHERE id='main'").get().payload, "{}");
  await writeAnimationSnapshot(db, snapshot("07", 0, 0));
  assert.deepEqual((await readAnimationSnapshot(db)).runs, []);
  assert.equal(db.database.prepare("SELECT count(*) AS total FROM monitor_snapshots").get().total, 2);
  db.database.close();
});

test("failed batch rolls back the manifest, rows and pruning together", async () => {
  const db = new LocalD1();
  const current = snapshot("06");
  await writeAnimationSnapshot(db, current);
  db.database.exec("CREATE TRIGGER fail_fixture BEFORE INSERT ON monitor_snapshots WHEN NEW.id='animation:run-30' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END");
  await assert.rejects(writeAnimationSnapshot(db, snapshot("07", 20)), /fixture failure/);
  assert.deepEqual(await readAnimationSnapshot(db), current);
  db.database.close();
});
