import { env } from "cloudflare:workers";

export function monitorDb() {
  if (!env.DB) throw new Error("Monitor storage unavailable");
  return env.DB;
}
export function writeToken(): string | undefined {
  return (env as { MONITOR_WRITE_TOKEN?: string }).MONITOR_WRITE_TOKEN;
}
