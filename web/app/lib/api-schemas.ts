/**
 * Zod schemas for runtime validation of critical API responses.
 *
 * Usage: wrap parsed JSON with .safeParse() for type-safe results.
 * Non-critical fields use .optional() to tolerate missing keys.
 */

import { z } from "zod/v4";

export const ProjectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().optional().default(""),
  table_count: z.number().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

export const ProjectListSchema = z.object({
  projects: z.array(ProjectSchema),
  limit: z.number().optional(),
  offset: z.number().optional(),
});

export const AuthTokenSchema = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
});

export const ConversationSchema = z.object({
  conversation_id: z.string(),
  file_id: z.string().nullable().optional(),
  project_id: z.string().nullable().optional(),
  table_id: z.string().nullable().optional(),
  title: z.string(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

export const ConversationListSchema = z.object({
  conversations: z.array(ConversationSchema),
  total: z.number().optional(),
});

export const MessageSchema = z.object({
  message_id: z.string(),
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  steps: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
  charts: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
  table_data: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
  suggestions: z.array(z.string()).nullable().optional(),
  created_at: z.string().optional(),
});

export const MessageListSchema = z.object({
  messages: z.array(MessageSchema),
});
