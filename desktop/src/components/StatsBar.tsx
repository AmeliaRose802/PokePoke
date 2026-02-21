/**
 * Stats bar component.
 *
 * Displays live session statistics: elapsed time, token counts,
 * API duration, items completed, retries, and agent run counts.
 */

import type { ModelPerformanceSummary,SessionStats } from "../types";
import {
  formatAgentRuns,
  formatDurationShort,
  formatElapsed,
  formatPercent,
  formatTotalTokens,
  getAddedCount,
  getAgentRunCounts,
  getCompletedItems,
  getDoneCount,
  getNetDelta,
  inferCurrentModel,
} from "../utils/stats";

interface Props {
  stats: SessionStats | null;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  activeAgentModel?: string | null;
  onOpenStats: () => void;
}

export function StatsBar({ stats, modelLeaderboard, activeAgentModel, onOpenStats }: Props) {
  const elapsed = stats?.elapsed_time ?? 0;
  const completedItems = getCompletedItems(stats);
  const doneCount = getDoneCount(stats);
  const addedCount = getAddedCount(stats);
  const netDelta = getNetDelta(stats);
  const apiDurationSeconds = stats?.agent_stats?.api_duration ?? 0;
  const apiDurationLabel =
    apiDurationSeconds > 0 ? formatDurationShort(apiDurationSeconds) : "\u2014";
  const currentModel = inferCurrentModel(stats, modelLeaderboard, activeAgentModel);
  const doneTooltip =
    completedItems.length > 0
      ? `Completed this session: ${completedItems.map((item) => item.id).join(", ")}`
      : "Counts items merged during this session";

  const modelStatusClass =
    currentModel.gatePassed === true
      ? "model-pass"
      : currentModel.gatePassed === false
        ? "model-fail"
        : "model-neutral";

  // New token and agent run metrics
  const totalTokens = formatTotalTokens(stats);
  const agentRunCounts = getAgentRunCounts(stats);
  const agentRunsDisplay = formatAgentRuns(agentRunCounts);

  return (
    <footer className="stats-bar compact">
      <div className="stats-summary">
        <div className="summary-block">
          <span className="summary-label">Uptime</span>
          <span className="summary-value">{formatElapsed(elapsed)}</span>
        </div>
        <div className="summary-block">
          <span className="summary-label">Added</span>
          <span className="summary-value">{addedCount}</span>
        </div>
        <div className="summary-block">
          <span className="summary-label">Done</span>
          <span className="summary-value" title={doneTooltip}>
            {doneCount}
          </span>
        </div>
        <div className="summary-block">
          <span className="summary-label">Net</span>
          <span className="summary-value">{netDelta >= 0 ? `+${netDelta}` : netDelta}</span>
        </div>
        <div className="summary-block">
          <span className="summary-label">API</span>
          <span className="summary-value">{apiDurationLabel}</span>
        </div>
        <div className="summary-block model-block">
          <span className="summary-label">Active model</span>
          <span className={`summary-value ${modelStatusClass}`}>
            {currentModel.model ?? "—"}
          </span>
          {currentModel.successRate !== null && (
            <span className="summary-subtext">
              {formatPercent(currentModel.successRate)}
            </span>
          )}
        </div>
        <div className="summary-block">
          <span className="summary-label">Tokens</span>
          <span className="summary-value">{totalTokens}</span>
        </div>
        <div className="summary-block">
          <span className="summary-label">Runs</span>
          <span className="summary-value">{agentRunsDisplay}</span>
        </div>
      </div>
      <button className="stats-link" onClick={onOpenStats} title="Open detailed stats">
        View full stats →
      </button>
    </footer>
  );
}
