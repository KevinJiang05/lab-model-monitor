CREATE TABLE `monitor_snapshots` (
	`id` text PRIMARY KEY NOT NULL,
	`payload` text NOT NULL,
	`generated_at` integer NOT NULL
);
