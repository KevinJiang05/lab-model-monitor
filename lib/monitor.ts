import { z } from "zod";

export const complete = new Set(["passed", "wrong_answer", "format_error"]);
const timestamp = z.string().datetime({ offset: true });
const sampleSchema = z.object({
  requested_model: z.string().min(1).max(200), returned_model: z.string().max(200),
  attempt: z.number().int().min(1).max(5), requested_at: timestamp,
  status: z.enum(["passed", "wrong_answer", "format_error", "timeout", "api_error", "incomplete"]),
  answer: z.number().int().min(0).max(999999).nullable(),
  elapsed_seconds: z.number().finite().min(0).max(86400),
  response_text: z.string().max(1600), response_truncated: z.boolean(),
  total_tokens: z.number().int().min(0).nullable(),
  http_status: z.number().int().min(400).max(599).nullable(),
});
export const snapshotSchema = z.object({
  schema_version: z.literal(1), synced_at: timestamp, timezone: z.literal("Asia/Taipei"),
  retention_days: z.literal(90), history_limited: z.boolean(),
  schedule: z.object({ enabled: z.boolean(), daily_time: z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/),
    daily_times: z.array(z.string().regex(/^(?:[01]\d|2[0-3]):[0-5]\d$/)).max(8).optional(),
    models: z.array(z.string().min(1).max(200)).min(1).max(10),
    attempts_per_model: z.number().int().min(1).max(5) }),
  method: z.object({ instructions: z.string().max(2000), prompt: z.string().max(10000) }),
  runs: z.array(z.object({
    run_id: z.string().uuid(), created_at: timestamp, ended_at: timestamp.nullable(),
    status: z.enum(["success", "failed", "cancelled"]), contract_id: z.string().regex(/^[0-9a-f]{64}$/),
    contract: z.object({
      prompt_version: z.string().max(200), prompt_sha256: z.string().regex(/^[0-9a-f]{64}$/),
      expected_answer: z.number().int(), api_mode: z.enum(["responses", "chat_completions"]),
      reasoning_effort: z.string().max(50), max_output_tokens: z.number().int().positive(),
      timeout_seconds: z.number().positive(), web_search: z.boolean(), stream_failure_retry: z.boolean(),
      stream: z.boolean().optional(),
    }), samples: z.array(sampleSchema).max(50),
  })).max(120),
}).superRefine((data, ctx) => {
  if (new Set(data.runs.map(r => r.run_id)).size !== data.runs.length)
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Duplicate run IDs" });
  if (data.runs.some(r => Date.parse(r.created_at) > Date.parse(data.synced_at) + 60000))
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Future run" });
});
export type Snapshot = z.infer<typeof snapshotSchema>;
export type Sample = Snapshot["runs"][number]["samples"][number];
export const statusText: Record<Sample["status"], string> = {
  passed: "通过", wrong_answer: "答案错误", format_error: "格式错误", timeout: "超时",
  api_error: "接口失败", incomplete: "回答截断",
};
export function summarize(samples: Sample[]) {
  const valid = samples.filter(s => complete.has(s.status));
  const passed = samples.filter(s => s.status === "passed").length;
  return { attempts: samples.length, completed: valid.length, passed,
    accuracy: valid.length ? 100 * passed / valid.length : null,
    availability: samples.length ? 100 * valid.length / samples.length : null,
    latency: samples.length ? samples.reduce((n,s) => n+s.elapsed_seconds,0)/samples.length : null,
  };
}
export function day(value: string) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}
export function formatTime(value: string | null) {
  return value ? new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Taipei", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)) : "—";
}
export function freshness(snapshot: Snapshot, now: Date) {
  if (!snapshot.schedule.enabled) return "paused";
  const local = new Date(now.getTime() + 8*3600000);
  const times = snapshot.schedule.daily_times?.length ? snapshot.schedule.daily_times : [snapshot.schedule.daily_time];
  const deadlines = times.flatMap(time => {
    const [hours, minutes] = time.split(":").map(Number);
    const today = Date.UTC(local.getUTCFullYear(),local.getUTCMonth(),local.getUTCDate(),hours-8,minutes);
    return [today - 86400000, today];
  });
  const due = Math.max(...deadlines.filter(d => now.getTime() >= d + 30*60000));
  const latest = snapshot.runs[0];
  return latest && Date.parse(latest.created_at) >= due ? "fresh" : "stale";
}
