/**
 * Runtime-validated schemas for Python ↔ TypeScript bridge payloads.
 *
 * These Zod schemas enforce contracts at the boundary between Python (DesktopAPI)
 * and TypeScript (useBridge). Any payload shape drift will fail fast with actionable
 * error messages instead of silently breaking the UI at render time.
 *
 * Usage:
 *   const validatedState = AppStateSchema.parse(rawState); // throws on mismatch
 *   const safeState = AppStateSchema.safeParse(rawState); // returns result object
 */

import { z } from "zod";

/** Log entry from the orchestrator or agent */
export const LogEntrySchema = z.object({
  message: z.string(),
  target: z.enum(["orchestrator", "agent"]),
  style: z.string().nullable(),
  timestamp: z.number(),
});

/** Current work item being processed */
export const WorkItemSchema = z.object({
  item_id: z.string(),
  title: z.string(),
  status: z.string(),
  labels: z.array(z.string()).optional(),
});

/** Agent execution statistics */
export const AgentStatsSchema = z.object({
  wall_duration: z.number(),
  api_duration: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  lines_added: z.number(),
  lines_removed: z.number(),
  premium_requests: z.number(),
  retries: z.number(),
  tool_calls: z.number(),
});

/** Record of a single work item completion for model A/B testing */
export const ModelCompletionRecordSchema = z.object({
  item_id: z.string(),
  model: z.string(),
  duration_seconds: z.number(),
  gate_passed: z.boolean().nullable(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  agent_turns: z.number(),
  cost: z.number(),
  retry_attempts: z.number(),
  api_duration: z.number().nullable(),
  lines_added: z.number().nullable(),
  lines_removed: z.number().nullable(),
});

/** Work item completed during the current session */
export const CompletedItemSchema = z.object({
  id: z.string(),
  title: z.string().optional(),
  status: z.string().optional(),
  issue_type: z.string().optional(),
});

/** Work item created during the current session (via bd create) */
export const CreatedItemSchema = z.object({
  id: z.string(),
  title: z.string().optional(),
  agent_type: z.string().optional(),
});

/** Historical model completion record with timestamp (from persistent store) */
export const ModelHistoryEntrySchema = ModelCompletionRecordSchema.extend({
  timestamp: z.string(),
  success: z.boolean().optional(),
  labels: z.array(z.string()).optional(),
  issue_type: z.string().optional(),
  item_type: z.string().optional(), // Alias for backward compatibility
});

/** Session-level statistics from the orchestrator */
export const SessionStatsSchema = z.object({
  elapsed_time: z.number(),
  agent_stats: AgentStatsSchema.optional(),
  items_completed: z.number().optional(),
  items_created: z.number().optional(),
  net_items_delta: z.number().optional(),
  lifetime_items_created: z.number().optional(),
  lifetime_items_completed: z.number().optional(),
  created_counts_by_agent_type: z.record(z.string(), z.number()).optional(),
  completed_counts_by_agent_type: z.record(z.string(), z.number()).optional(),
  completed_items: z.array(CompletedItemSchema).optional(),
  created_items: z.array(CreatedItemSchema).optional(),
  work_agent_runs: z.number().optional(),
  gate_agent_runs: z.number().optional(),
  tech_debt_agent_runs: z.number().optional(),
  janitor_agent_runs: z.number().optional(),
  backlog_cleanup_agent_runs: z.number().optional(),
  cleanup_agent_runs: z.number().optional(),
  beta_tester_agent_runs: z.number().optional(),
  code_review_agent_runs: z.number().optional(),
  worktree_cleanup_agent_runs: z.number().optional(),
  agent_type_elapsed_seconds: z.record(z.string(), z.number()).optional(),
  model_completions: z.array(ModelCompletionRecordSchema).optional(),
  gate_rejections: z.number().optional(),
  gate_checks: z.number().optional(),
});

/** Progress indicator state */
export const ProgressStateSchema = z.object({
  active: z.boolean(),
  status: z.string(),
});

/** Prompt template metadata from the Python PromptService */
export const PromptInfoSchema = z.object({
  name: z.string(),
  is_override: z.boolean(),
  has_builtin: z.boolean(),
  source: z.enum(["user", "builtin"]),
});

/** Full prompt detail including content and template variables */
export const PromptDetailSchema = PromptInfoSchema.extend({
  content: z.string(),
  template_variables: z.array(z.string()),
});

/** Connection status of the pywebview bridge */
export const ConnectionStatusSchema = z.enum(["connecting", "connected", "disconnected"]);

/** Maintenance agent configuration */
export const MaintenanceAgentSchema = z.object({
  name: z.string(),
  prompt_file: z.string(),
  frequency: z.number(),
  enabled: z.boolean(),
  needs_worktree: z.boolean(),
  merge_changes: z.boolean().optional(),
  model: z.string().optional(),
  custom: z.boolean().optional(),
  description: z.string().optional(),
});

/** Maintenance configuration section */
export const MaintenanceConfigSchema = z.object({
  agents: z.array(MaintenanceAgentSchema),
});

/** MCP server configuration */
export const McpServerConfigSchema = z.object({
  enabled: z.boolean().optional(),
  restart_script: z.string().optional(),
  name: z.string().optional(),
});

/** Model configuration section of project config */
export const ModelsConfigSchema = z.object({
  default: z.string().optional(),
  fallback: z.string().optional(),
  ab_testing_enabled: z.boolean().optional(),
  candidate_models: z.array(z.string()).optional(),
});

/** Project configuration from .pokepoke/config.yaml */
export const ProjectConfigSchema = z.object({
  project_name: z.string().optional(),
  models: ModelsConfigSchema.optional(),
  git: z.record(z.string(), z.unknown()).optional(),
  mcp_server: McpServerConfigSchema.optional(),
  maintenance: MaintenanceConfigSchema.optional(),
  test_data: z.record(z.string(), z.string()).optional(),
  max_parallel_agents: z.number().optional(),
}).passthrough(); // Allow additional unknown fields

/** Response from get_config API */
export const ConfigResponseSchema = z.object({
  path: z.string(),
  config: ProjectConfigSchema,
  exists: z.boolean(),
});

/** Setup status from the first-time wizard */
export const SetupStatusSchema = z.object({
  cwd: z.string(),
  project_root: z.string(),
  is_git_repo: z.boolean(),
  beads_installed: z.boolean(),
  beads_initialized: z.boolean(),
  config_exists: z.boolean(),
  config_path: z.string(),
  needs_setup: z.boolean(),
});

/** Setup configuration payload for creating default config */
export const SetupConfigPayloadSchema = z.object({
  project_name: z.string(),
  default_model: z.string(),
  fallback_model: z.string().optional(),
  max_parallel_agents: z.number(),
  default_branch: z.string().optional(),
});

/** Response from check_for_updates API */
export const UpdateCheckResultSchema = z.object({
  current_version: z.string(),
  latest_version: z.string().optional(),
  update_available: z.boolean(),
  download_url: z.string().optional(),
  error: z.string().optional(),
});

/** Response from get_available_models API */
export const AvailableModelsResponseSchema = z.object({
  models: z.array(z.string()),
  last_sync: z.string().nullable(),
  removed_from_config: z.array(z.string()),
});

/** All-time per-model performance summary from persistent storage */
export const ModelPerformanceSummarySchema = z.object({
  total_items_attempted: z.number(),
  total_items_succeeded: z.number(),
  total_items_failed: z.number(),
  total_duration_seconds: z.number(),
  total_retries: z.number(),
  average_duration: z.number(),
  median_duration: z.number().optional(),
  stddev_duration: z.number().optional(),
  success_rate: z.number(),
  last_used: z.string(),
});

/** Running agent info from the orchestrator */
export const AgentInfoSchema = z.object({
  agent_id: z.string(),
  base_agent_id: z.string().nullable().optional(),
  card_id: z.string().nullable().optional(),
  parent_card_id: z.string().nullable().optional(),
  name: z.string(),
  iteration: z.number(),
  status: z.enum(["running", "success", "failed"]),
  model: z.string().nullable().optional(),
  parent_agent_id: z.string().nullable().optional(),
  work_item_id: z.string().nullable().optional(),
  work_item_title: z.string().nullable().optional(),
  agent_type: z.string().nullable().optional(),
  modified_files: z.array(z.string()).optional(),
  recent_logs: z.array(z.string()),
  log_lines: z.array(z.string()).optional(),
  agent_prompt: z.string().nullable().optional(),
  started_at: z.number().optional(),
  last_updated: z.number().optional(),
  last_log_at: z.number().nullable().optional(),
  paused: z.boolean().optional(),
  session_id: z.string().nullable().optional(),
  input_tokens: z.number().optional(),
  output_tokens: z.number().optional(),
  is_history_entry: z.boolean().optional(),
});

/** State snapshot from the bridge */
export const AppStateSchema = z.object({
  work_item: WorkItemSchema.nullable(),
  agent_name: z.string(),
  repository_name: z.string(),
  stats: SessionStatsSchema.nullable(),
  progress: ProgressStateSchema,
  log_count: z.number(),
  model_leaderboard: z.record(z.string(), ModelPerformanceSummarySchema), // Allow any string keys
  agents: z.array(AgentInfoSchema),
  stop_after_current: z.boolean(),
  project_name: z.string().optional(),
  current_session_id: z.string().nullable(),
  logs_dir: z.string().nullable(),
  new_logs: z.array(LogEntrySchema).optional(),
});

// ── Merge Workflow Visualization Schemas ─────────────────────────────

/** State of a single merge workflow step */
export const MergeStepStateSchema = z.object({
  step_id: z.string(),
  label: z.string(),
  status: z.enum(["pending", "active", "done", "failed", "skipped"]),
  started_at: z.number().nullable(),
  ended_at: z.number().nullable(),
  logs: z.array(z.string()),
});

/** A single merge run */
export const MergeFlowRunSchema = z.object({
  agent_id: z.string(),
  item_id: z.string(),
  started_at: z.number(),
  ended_at: z.number().nullable(),
  outcome: z.enum(["in_progress", "success", "failed"]),
  steps: z.record(z.string(), MergeStepStateSchema),
});

/** Step definition from canonical step list */
export const MergeStepDefSchema = z.object({
  id: z.string(),
  label: z.string(),
});

/** Edge between two merge steps */
export const MergeEdgeSchema = z.object({
  from: z.string(),
  to: z.string(),
  label: z.string().optional(),
});

/** Full merge flow state */
export const MergeFlowStateSchema = z.object({
  current_run: MergeFlowRunSchema.nullable(),
  last_completed_run: MergeFlowRunSchema.nullable(),
  steps_definition: z.array(MergeStepDefSchema),
  edges: z.array(MergeEdgeSchema),
});

/** Combined pipeline state (gate + merge) */
export const PipelineStateSchema = z.object({
  gate: MergeFlowStateSchema,
  merge: MergeFlowStateSchema,
  active_phase: z.enum(["idle", "gate", "merge"]),
});

/**
 * Helper to validate and provide detailed error messages
 */
export function validatePayload<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  context: string
): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    const errorDetails = result.error.issues
      .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
      .join("; ");
    throw new Error(`[Bridge Contract Error] ${context} failed validation: ${errorDetails}`);
  }
  return result.data;
}

/**
 * Safe validation that returns null on error (for non-critical payloads)
 */
export function safeValidatePayload<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  context: string
): T | null {
  const result = schema.safeParse(data);
  if (!result.success) {
    console.error(
      `[Bridge Contract Warning] ${context} validation failed:`,
      result.error.issues
    );
    return null;
  }
  return result.data;
}
