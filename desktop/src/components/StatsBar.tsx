/**
 * Stats bar component.
 *
 * Displays live session statistics: elapsed time, token counts,
 * API duration, items completed, retries, and agent run counts.
 */

import type { SessionStats, ModelPerformanceSummary } from "../types";
import { formatElapsed, formatPercent, inferCurrentModel } from "../utils/stats";

interface Props {
  stats: SessionStats | null;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  onOpenStats: () => void;
}

export function StatsBar({ stats, modelLeaderboard, onOpenStats }: Props) {
  const elapsed = stats?.elapsed_time ?? 0;
  const doneCount = stats?.items_completed ?? 0;
  const currentModel = inferCurrentModel(stats, modelLeaderboard);

  const modelStatusClass =
    currentModel.gatePassed === true
      ? "model-pass"
      : currentModel.gatePassed === false
        ? "model-fail"
        : "model-neutral";

  return (
    <footer className="stats-bar compact">
      <div className="stats-summary">
        <div className="summary-block">
          <span className="summary-label">Uptime</span>
          <span className="summary-value">{formatElapsed(elapsed)}</span>
        </div>
        <div className="summary-block">
          <span className="summary-label">Done</span>
          <span className="summary-value">{doneCount}</span>
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
      </div>
      <button className="stats-link" onClick={onOpenStats} title="Open detailed stats">
        View full stats →
      </button>
    </footer>
  );
}
