import { integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const monitorSnapshots = sqliteTable("monitor_snapshots", {
  id: text("id").primaryKey(),
  payload: text("payload").notNull(),
  generatedAt: integer("generated_at").notNull(),
});
