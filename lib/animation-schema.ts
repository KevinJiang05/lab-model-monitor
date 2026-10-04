import { z } from "zod";

export const animationRunSchema = z.object({
  run_id: z.string().uuid(), created_at: z.string().datetime({ offset: true }),
  prompt: z.string().max(10000), instructions: z.string().max(2000),
  reasoning_effort: z.string().max(20), stream: z.boolean(), max_output_tokens: z.number().int().positive(),
  samples: z.array(z.object({
    requested_model: z.string().max(200), returned_model: z.string().max(200),
    requested_at: z.string().datetime({ offset: true }).nullable().optional(),
    attempt: z.number().int().min(1).max(3).nullable().optional(),
    status: z.enum(["generated", "incomplete", "format_error", "timeout", "api_error"]),
    elapsed_seconds: z.number().finite().min(0),
    input_tokens: z.number().int().min(0).nullable(), output_tokens: z.number().int().min(0).nullable(),
    total_tokens: z.number().int().min(0).nullable(), completion_status: z.string().max(100),
    html: z.string().max(120000).nullable(), sha256: z.string().regex(/^[a-f0-9]{64}$/).nullable(),
    thumbnail: z.string().max(240022).regex(/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/).nullable().optional(),
    http_status: z.string().regex(/^[45]\d\d$/).nullable(),
  })).max(30),
});
export const animationSnapshotSchema = z.object({
  kind: z.literal("animation"), schema_version: z.literal(1),
  synced_at: z.string().datetime({ offset: true }), runs: z.array(animationRunSchema).max(12),
}).refine(value => new TextEncoder().encode(JSON.stringify(value)).length <= 900000, "Animation snapshot too large");
export type AnimationRun = z.infer<typeof animationRunSchema>;
