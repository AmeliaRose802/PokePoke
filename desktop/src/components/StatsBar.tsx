/**
 * Stats bar component.
 *
 * Displays live session statistics: elapsed time, token counts,
 * API duration, items completed, retries, and agent run counts.
 */

import type { SessionStats, ModelCompletionRecord } from "../types";

interface Props {
  stats: SessionStats | null;
}

function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return String(count);
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Summarize model completions into per-model aggregates. */
function summarizeModels(
  completions: ModelCompletionRecord[]
): { model: string; count: number; avgTime: number; passRate: number | null }[] {
  const byModel = new Map<string, ModelCompletionRecord[]>();
  for (const rec of completions) {
    const list = byModel.get(rec.model) ?? [];
    list.push(rec);
    byModel.set(rec.model, list);
  }
  return Array.from(byModel.entries()).map(([model, recs]) => {
    const avgTime = recs.reduce((s, r) => s + r.duration_seconds, 0) / recs.length;
    const gated = recs.filter((r) => r.gate_passed !== null);
    const passRate =
      gated.length > 0
        ? Math.round((gated.filter((r) => r.gate_passed).length / gated.length) * 100)
        : null;
    return { model, count: recs.length, avgTime, passRate };
  });
}

export function StatsBar({ stats }: Props) {
  const agent = stats?.agent_stats;
  const elapsed = stats?.elapsed_time ?? 0;
  const modelSummary = summarizeModels(stats?.model_completions ?? []);

  return (
    <footer className="stats-bar">
      {/* Row 1: Time and API stats */}
      <div className="stats-row">
        <span className="stat">
          <span className="stat-icon">⏱️</span>
          <span className="stat-value elapsed">{formatElapsed(elapsed)}</span>
        </span>
        <span className="stat">
          <span className="stat-icon">⚡</span>
          <span className="stat-label">API:</span>
          <span className="stat-value api">
            {formatDuration(agent?.api_duration ?? 0)}
          </span>
        </span>
        <span className="stat">
          <span className="stat-icon">📥</span>
          <span className="stat-value input-tokens">
            {formatTokens(agent?.input_tokens ?? 0)}
          </span>
        </span>
        <span className="stat">
          <span className="stat-icon">📤</span>
          <span className="stat-value output-tokens">
            {formatTokens(agent?.output_tokens ?? 0)}
          </span>
        </span>
        <span className="stat">
          <span className="stat-icon">🔧</span>
          <span className="stat-value">{agent?.tool_calls ?? 0}</span>
        </span>
      </div>

      {/* Row 2: Completion stats */}
      <div className="stats-row">
        <span className="stat">
          <span className="stat-icon">✅</span>
          <span className="stat-label">Done:</span>
          <span className="stat-value done">
            {stats?.items_completed ?? 0}
          </span>
        </span>
        <span className="stat">
          <span className="stat-icon">🔄</span>
          <span className="stat-label">Retries:</span>
          <span
            className={`stat-value ${
              (agent?.retries ?? 0) > 3
                ? "retries-high"
                : (agent?.retries ?? 0) > 0
                  ? "retries-warn"
                  : ""
            }`}
          >
            {agent?.retries ?? 0}
          </span>
        </span>
      </div>

      {/* Row 3: Agent run counts */}
      <div className="stats-row agent-runs">
        <span className="stat">
          👷 Work:{stats?.work_agent_runs ?? 0}
        </span>
        <span className="stat">
          🚪 Gate:{stats?.gate_agent_runs ?? 0}
        </span>
        <span className="stat">
          💸 Debt:{stats?.tech_debt_agent_runs ?? 0}
        </span>
        <span className="stat">
          🧹 Jan:{stats?.janitor_agent_runs ?? 0}
        </span>
        <span className="stat">
          🗄️ Blog:{stats?.backlog_cleanup_agent_runs ?? 0}
        </span>
        <span className="stat">
          🧼 Cln:{stats?.cleanup_agent_runs ?? 0}
        </span>
        <span className="stat">
          🧪 Beta:{stats?.beta_tester_agent_runs ?? 0}
        </span>
        <span className="stat">
          🔍 Rev:{stats?.code_review_agent_runs ?? 0}
        </span>
      </div>

      {/* Row 4: Model comparison (A/B testing) */}
      {modelSummary.length > 0 && (
        <div className="stats-row model-comparison">
          <span className="stat-icon">🔬</span>
          {modelSummary.map(({ model, count, avgTime, passRate }) => (
            <span key={model} className="stat model-stat">
              <span className="stat-label">{model}:</span>
              <span className="stat-value">
                {count}× {formatDuration(avgTime)}
                {passRate !== null && ` (${passRate}%)`}
              </span>
            </span>
          ))}
        </div>
      )}
    </footer>
  );
}
