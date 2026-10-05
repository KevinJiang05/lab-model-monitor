import { timingSafeEqual } from "node:crypto";
import { monitorDb, writeToken } from "@/db/monitor";
import { writeAnimationSnapshot } from "@/db/animation";
import { animationSnapshotSchema, MAX_ANIMATION_SNAPSHOT_BYTES } from "@/lib/animation-schema";
import { snapshotSchema } from "@/lib/monitor";

export async function POST(request: Request) {
  const token = writeToken();
  const actual = Buffer.from(request.headers.get("Authorization") || "");
  const expected = Buffer.from(`Bearer ${token}`);
  if (!token || actual.length !== expected.length || !timingSafeEqual(actual,expected))
    return Response.json({ success: false, error: "unauthorized" }, { status: 401 });
  const limit = MAX_ANIMATION_SNAPSHOT_BYTES;
  if (Number(request.headers.get("Content-Length")) > limit)
    return Response.json({ success: false, error: "too_large" }, { status: 413 });
  try {
    const reader = request.body?.getReader();
    if (!reader) return Response.json({ success: false, error: "empty_body" }, { status: 400 });
    const chunks: Uint8Array[] = []; let size = 0;
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); return Response.json({ success: false, error: "too_large" }, { status: 413 }); }
      chunks.push(value);
    }
    let parsed: unknown;
    try {
      const body = Buffer.concat(chunks);
      chunks.length = 0;
      parsed = JSON.parse(body.toString("utf8"));
    }
    catch { return Response.json({ success: false, error: "invalid_json" }, { status: 400 }); }
    const isAnimation = !!parsed && typeof parsed === "object" && "kind" in parsed && parsed.kind === "animation";
    const validated = isAnimation ? animationSnapshotSchema.safeParse(parsed) : snapshotSchema.safeParse(parsed);
    if (!validated.success) return Response.json({ success: false, error: "invalid_snapshot" }, { status: 400 });
    const snapshot = validated.data;
    const stamp = Date.parse(snapshot.synced_at);
    if (stamp > Date.now() + 60000) return Response.json({ success: false, error: "future_snapshot" }, { status: 400 });
    snapshot.runs.sort((a,b) => Date.parse(b.created_at) - Date.parse(a.created_at));
    if ("kind" in snapshot) {
      const updated = await writeAnimationSnapshot(monitorDb(), snapshot);
      if (!updated) return Response.json({ success: false, error: "older_snapshot" }, { status: 409 });
      return Response.json({ success: true, runs: snapshot.runs.length });
    }
    const result = await monitorDb().prepare(`INSERT INTO monitor_snapshots (id, payload, generated_at) VALUES (?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, generated_at = excluded.generated_at
      WHERE excluded.generated_at >= monitor_snapshots.generated_at`).bind("main", JSON.stringify(snapshot), stamp).run();
    if (!result.meta.changes) return Response.json({ success: false, error: "older_snapshot" }, { status: 409 });
    return Response.json({ success: true, runs: snapshot.runs.length });
  } catch {
    console.error("Monitor snapshot write failed");
    return Response.json({ success: false, error: "storage_unavailable" }, { status: 503 });
  }
}
