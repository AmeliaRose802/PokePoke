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

/** Session-level statistics from the orchestrator */
export interface SessionStats {
  elapsed_time: number;
  agent_stats?: AgentStats;
  items_completed?: number;
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

/** Connection status of the pywebview bridge */
export type ConnectionStatus = "connecting" | "connected" | "disconnected";

/** All-time per-model performance summary from persistent storage */
export interface ModelPerformanceSummary {
  total_items_attempted: number;
  total_items_succeeded: number;
  total_items_failed: number;
  total_duration_seconds: number;
  total_retries: number;
  average_duration: number;
  success_rate: number;
  last_used: string;
}
