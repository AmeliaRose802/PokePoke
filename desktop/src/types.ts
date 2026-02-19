/**
 * Shared types for PokePoke desktop frontend.
 *
 * These mirror the Python-side DesktopAPI data structures.
 * Communication is via direct in-process calls through pywebview.
 */

/** Log entry from the orchestrator or agent */
export interface LogEntry {
  message: string;
  target: "orchestrator" | "agent";
  style: string | null;
  timestamp: number;
}

/** Current work item being processed */
export interface WorkItem {
  item_id: string;
  title: string;
  status: string;
}

/** Agent execution statistics */
export interface AgentStats {
  wall_duration: number;
  api_duration: number;
  input_tokens: number;
  output_tokens: number;
  lines_added: number;
  lines_removed: number;
  premium_requests: number;
  retries: number;
  tool_calls: number;
}

/** Record of a single work item completion for model A/B testing */
export interface ModelCompletionRecord {
  item_id: string;
  model: string;
  duration_seconds: number;
  gate_passed: boolean | null;
}

/** Work item completed during the current session */
export interface CompletedItem {
  id: string;
  title?: string;
  status?: string;
  issue_type?: string;
}

/** Historical model completion record with timestamp (from persistent store) */
export interface ModelHistoryEntry extends ModelCompletionRecord {
  timestamp: string;
}

/** Session-level statistics from the orchestrator */
export interface SessionStats {
  elapsed_time: number;
  agent_stats?: AgentStats;
  items_completed?: number;
  completed_items?: CompletedItem[];
  work_agent_runs?: number;
  gate_agent_runs?: number;
  tech_debt_agent_runs?: number;
  janitor_agent_runs?: number;
  backlog_cleanup_agent_runs?: number;
  cleanup_agent_runs?: number;
  beta_tester_agent_runs?: number;
  code_review_agent_runs?: number;
  worktree_cleanup_agent_runs?: number;
  model_completions?: ModelCompletionRecord[];
}

/** Progress indicator state */
export interface ProgressState {
  active: boolean;
  status: string;
}

/** Prompt template metadata from the Python PromptService */
export interface PromptInfo {
  name: string;
  is_override: boolean;
  has_builtin: boolean;
  source: "user" | "builtin";
}

/** Full prompt detail including content and template variables */
export interface PromptDetail extends PromptInfo {
  content: string;
  template_variables: string[];
}

/** Connection status of the pywebview bridge */
export type ConnectionStatus = "connecting" | "connected" | "disconnected";

/** Maintenance agent configuration */
export interface MaintenanceAgent {
  name: string;
  prompt_file: string;
  frequency: number;
  enabled: boolean;
  needs_worktree: boolean;
  merge_changes?: boolean;
  model?: string;
}

/** Maintenance configuration section */
export interface MaintenanceConfig {
  agents: MaintenanceAgent[];
}

/** MCP server configuration section */
export interface McpServerConfig {
  enabled?: boolean;
  name?: string;
  restart_script?: string;
}

/** Project configuration from .pokepoke/config.yaml */
export interface ProjectConfig {
  project_name?: string;
  models?: ModelsConfig;
  git?: Record<string, unknown>;
  mcp_server?: McpServerConfig;
  maintenance?: MaintenanceConfig;
  test_data?: Record<string, string>;
  [key: string]: unknown;
}

/** Model configuration section of project config */
export interface ModelsConfig {
  default?: string;
  fallback?: string;
  candidate_models?: string[];
}

/** Response from get_config API */
export interface ConfigResponse {
  path: string;
  config: ProjectConfig;
  exists: boolean;
}

/** All-time per-model performance summary from persistent storage */
export interface ModelPerformanceSummary {
  total_items_attempted: number;
  total_items_succeeded: number;
  total_items_failed: number;
  total_duration_seconds: number;
  total_retries: number;
  average_duration: number;
  median_duration?: number;
  stddev_duration?: number;
  success_rate: number;
  last_used: string;
}

/** Running agent info from the orchestrator */
export interface AgentInfo {
  agent_id: string;
  name: string;
  iteration: number;
  status: "running" | "success" | "failed";
  model?: string | null;
  parent_agent_id?: string | null;
   work_item_id?: string | null;
   work_item_title?: string | null;
  recent_logs: string[];
  log_lines?: string[];
  started_at?: number;
  last_updated?: number;
  last_log_at?: number | null;
}
