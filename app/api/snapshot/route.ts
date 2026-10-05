import { monitorDb } from "@/db/monitor";
import { readAnimationSnapshot } from "@/db/animation";

export async function GET(request: Request) {
  try {
    const animation = new URL(request.url).searchParams.get("test") === "animation";
    const row = animation ? null : await monitorDb().prepare("SELECT payload FROM monitor_snapshots WHERE id = 'main'").first<{ payload: string }>();
    const snapshot = animation ? await readAnimationSnapshot(monitorDb()) : row ? JSON.parse(row.payload) : null;
    return Response.json({ success: true, snapshot }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    console.error("Monitor snapshot read failed");
    return Response.json({ success: false, error: "storage_unavailable" }, { status: 503 });
  }
}
