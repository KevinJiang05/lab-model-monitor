// Intentionally empty by default.
// Add Drizzle tables here when the site actually needs a database.
// See examples/d1/db/schema.ts for an opt-in example.
export {};
import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const monitorSnapshots = sqliteTable("monitor_snapshots", {
  id: text("id").primaryKey(),
  payload: text("payload").notNull(),
  generatedAt: integer("generated_at").notNull(),
});
