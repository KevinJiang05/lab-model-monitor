import type { D1Database } from "@cloudflare/workers-types";
import type { AnimationSnapshot } from "@/lib/animation-schema";

type Manifest = Omit<AnimationSnapshot, "runs"> & { storage_version: 2; run_ids: string[] };

export async function readAnimationSnapshot(db: D1Database): Promise<AnimationSnapshot | null> {
  // One SELECT sees the manifest and its rows together, including during sync.
  const { results } = await db.prepare(`SELECT id, payload FROM monitor_snapshots
    WHERE id = 'animation' OR (id LIKE 'animation:%' AND generated_at =
      (SELECT generated_at FROM monitor_snapshots WHERE id = 'animation'))`)
    .all<{ id: string; payload: string }>();
  const header = results.find(row => row.id === "animation");
  if (!header) return null;
  const manifest = JSON.parse(header.payload) as Manifest | AnimationSnapshot;
  // Existing deployments keep working before their first sync in the new format.
  if (!("storage_version" in manifest)) return manifest;
  const rows = new Map(results.map(row => [row.id, row.payload]));
  return {
    kind: manifest.kind, schema_version: manifest.schema_version, synced_at: manifest.synced_at,
    runs: manifest.run_ids.map(id => {
      const payload = rows.get(`animation:${id}`);
      if (!payload) throw new Error("Animation display row missing");
      return JSON.parse(payload);
    }),
  };
}

export async function writeAnimationSnapshot(db: D1Database, snapshot: AnimationSnapshot): Promise<boolean> {
  const stamp = Date.parse(snapshot.synced_at);
  const manifest: Manifest = {
    kind: snapshot.kind, schema_version: snapshot.schema_version, synced_at: snapshot.synced_at,
    storage_version: 2, run_ids: snapshot.runs.map(run => run.run_id),
  };
  const current = "EXISTS (SELECT 1 FROM monitor_snapshots WHERE id = 'animation' AND generated_at = ?)";
  const statements = [db.prepare(`INSERT INTO monitor_snapshots (id, payload, generated_at) VALUES ('animation', ?, ?)
    ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, generated_at = excluded.generated_at
    WHERE excluded.generated_at >= monitor_snapshots.generated_at`).bind(JSON.stringify(manifest), stamp)];
  for (const run of snapshot.runs) {
    statements.push(db.prepare(`INSERT INTO monitor_snapshots (id, payload, generated_at)
      SELECT ?, ?, ? WHERE ${current}
      ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, generated_at = excluded.generated_at
      WHERE excluded.generated_at >= monitor_snapshots.generated_at`)
      .bind(`animation:${run.run_id}`, JSON.stringify(run), stamp, stamp));
  }
  // Remove only obsolete cloud display rows, in the same transaction as the
  // new manifest. An older delivery cannot replace or prune newer results.
  const ids = snapshot.runs.map(run => `animation:${run.run_id}`);
  const keep = ids.length ? `AND id NOT IN (${ids.map(() => "?").join(",")})` : "";
  statements.push(db.prepare(`DELETE FROM monitor_snapshots
    WHERE id LIKE 'animation:%' ${keep} AND ${current}`).bind(...ids, stamp));
  const results = await db.batch(statements);
  return !!results[0].meta.changes;
}
