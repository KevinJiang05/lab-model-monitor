import { monitorDb } from "@/db/monitor";

export async function GET() {
  try {
    const row = await monitorDb().prepare("SELECT payload FROM monitor_snapshots WHERE id = ?").bind("main").first<{ payload: string }>();
    return Response.json({ success: true, snapshot: row ? JSON.parse(row.payload) : null }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    console.error("Monitor snapshot read failed");
    return Response.json({ success: false, error: "storage_unavailable" }, { status: 503 });
  }
}
