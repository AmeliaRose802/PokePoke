import { useMemo, useState } from "react";
import type {
  ModelHistoryEntry,
  ModelPerformanceSummary,
  SessionStats,
} from "../types";
import {
  formatDurationShort,
  formatElapsed,
  formatPercent,
  formatTokens,
  inferCurrentModel,
} from "../utils/stats";

interface StatsPageProps {
  stats: SessionStats | null;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  modelHistory: ModelHistoryEntry[];
  historyLoading: boolean;
  historyError: string | null;
  onRefreshHistory: () => void;
  onClose: () => void;
}

type SortField = "model" | "runs" | "success" | "duration";

interface TrendPoint {
  label: string;
  value: number;
}

interface AgentSegment {
  label: string;
  value: number;
  color: string;
}

interface AgentActivity {
  total: number;
  segments: AgentSegment[];
}

interface NormalizedAgentSegment extends AgentSegment {
  start: number;
  width: number;
}

export function StatsPage({
  stats,
  modelLeaderboard,
  modelHistory,
  historyLoading,
  historyError,
  onRefreshHistory,
  onClose,
}: StatsPageProps) {
  const agent = stats?.agent_stats;
  const sessionCards = [
    { label: "Done", value: stats?.items_completed ?? 0, icon: "✅" },
    { label: "Retries", value: agent?.retries ?? 0, icon: "🔁" },
    { label: "API Calls", value: agent?.premium_requests ?? 0, icon: "📡" },
    { label: "API seconds", value: (agent?.api_duration ?? 0) > 0 ? formatDurationShort(agent?.api_duration) : "—", icon: "⚡" },
    {
      label: "Tokens",
      value: formatTokens((agent?.input_tokens ?? 0) + (agent?.output_tokens ?? 0)),
      icon: "🧮",
    },
    { label: "Tool Calls", value: agent?.tool_calls ?? 0, icon: "🛠️" },
    { label: "Uptime", value: formatElapsed(stats?.elapsed_time ?? 0), icon: "⏱️" },
  ];

  const agentActivity = buildAgentActivity(stats);
  const normalizedSegments = normalizeAgentSegments(agentActivity);
  const currentModel = inferCurrentModel(stats, modelLeaderboard);

  const [sortField, setSortField] = useState<SortField>("success");
  const [sortAsc, setSortAsc] = useState(false);

  const leaderboardRows = useMemo(() => {
    const rows = Object.entries(modelLeaderboard ?? {}).map(([model, summary]) => ({
      model,
      runs: summary.total_items_attempted ?? 0,
      successRate: summary.success_rate ?? 0,
      avgDuration: summary.average_duration ?? 0,
    }));

    const sorted = [...rows].sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case "runs":
          comparison = a.runs - b.runs;
          break;
        case "success":
          comparison = a.successRate - b.successRate;
          break;
        case "duration":
          comparison = a.avgDuration - b.avgDuration;
          break;
        default:
          comparison = a.model.localeCompare(b.model);
      }
      return sortAsc ? comparison : -comparison;
    });

    return sorted;
  }, [modelLeaderboard, sortField, sortAsc]);

  const completionSeries = useMemo(() => buildCompletionSeries(modelHistory), [modelHistory]);
  const successSeries = useMemo(() => buildSuccessRateSeries(modelHistory), [modelHistory]);

  const handleSort = (field: SortField) => {
    if (field === sortField) {
      setSortAsc((prev) => !prev);
    } else {
      setSortField(field);
      setSortAsc(field === "model"); // default ascending for name, descending otherwise
    }
  };

  return (
    <div className="stats-overlay" role="dialog" aria-modal="true">
      <div className="stats-panel">
        <div className="stats-panel-header">
          <div>
            <h2>Session Stats</h2>
            <p>Live metrics, historical performance, and model insights.</p>
          </div>
          <button className="stats-close-btn" onClick={onClose} aria-label="Close stats">
            ✕
          </button>
        </div>

        <div className="stats-actions-row">
          <div>
            <button className="stats-refresh-btn" onClick={onRefreshHistory} disabled={historyLoading}>
              {historyLoading ? "Refreshing…" : "Refresh history"}
            </button>
            {historyError && <span className="stats-error">{historyError}</span>}
          </div>
          <span className="stats-note">History powered by persistent model completions log.</span>
        </div>

        <div className="stats-content">
          <section>
            <h3>Session summary</h3>
            <div className="stats-card-grid">
              {sessionCards.map((card) => (
                <div key={card.label} className="stats-card">
                  <span className="stats-card-icon">{card.icon}</span>
                  <div className="stats-card-body">
                    <span className="stats-card-label">{card.label}</span>
                    <span className="stats-card-value">{card.value}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="stats-flex-row">
            <div className="stats-panel-card">
              <div className="stats-panel-card-header">
                <h3>Agent activity</h3>
                <span className="stats-panel-subtitle">Work vs maintenance vs review</span>
              </div>
              {agentActivity.total > 0 ? (
                <>
                  <div className="agent-activity-bar">
                    <svg viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label="Agent activity distribution">
                      {normalizedSegments.map((segment) => (
                        <rect
                          key={segment.label}
                          x={segment.start}
                          y={0}
                          width={segment.width}
                          height={10}
                          fill={segment.color}
                        >
                          <title>{`${segment.label}: ${segment.value}`}</title>
                        </rect>
                      ))}
                    </svg>
                  </div>
                  <div className="agent-activity-legend">
                    {normalizedSegments.map((segment) => (
                      <span key={segment.label} className="agent-activity-pill">
                        <span className="agent-legend-dot" aria-hidden="true">
                          <svg viewBox="0 0 8 8" preserveAspectRatio="none">
                            <circle cx="4" cy="4" r="4" fill={segment.color} />
                          </svg>
                        </span>
                        {segment.label}: {segment.value}
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <p className="stats-empty">No agent runs recorded yet.</p>
              )}
            </div>

            <div className="stats-panel-card">
              <div className="stats-panel-card-header">
                <h3>Current model assignment</h3>
                <span className="stats-panel-subtitle">Live selection + success signal</span>
              </div>
              <div className="current-model-card">
                <div className="model-row">
                  <span className="model-label">Model</span>
                  <span className={`model-value ${statusClass(currentModel.gatePassed)}`}>
                    {currentModel.model ?? "No runs yet"}
                  </span>
                </div>
                <div className="model-row">
                  <span className="model-label">Gate status</span>
                  <span className={`model-status-indicator ${statusClass(currentModel.gatePassed)}`}>
                    {gateStatusText(currentModel.gatePassed)}
                  </span>
                </div>
                <div className="model-row">
                  <span className="model-label">All-time success</span>
                  <span className="model-value">
                    {formatPercent(currentModel.successRate, 1)}
                  </span>
                </div>
              </div>
            </div>
          </section>

          <section>
            <div className="stats-panel-card">
              <div className="stats-panel-card-header">
                <h3>All-time model performance</h3>
                <span className="stats-panel-subtitle">Sortable leaderboard with success bars</span>
              </div>
              {leaderboardRows.length === 0 ? (
                <p className="stats-empty">No model history yet.</p>
              ) : (
                <div className="model-table-wrapper">
                  <table className="model-table">
                    <thead>
                      <tr>
                        <SortableHead
                          label="Model"
                          field="model"
                          activeField={sortField}
                          asc={sortAsc}
                          onSort={handleSort}
                        />
                        <SortableHead
                          label="Runs"
                          field="runs"
                          activeField={sortField}
                          asc={sortAsc}
                          onSort={handleSort}
                        />
                        <SortableHead
                          label="Success rate"
                          field="success"
                          activeField={sortField}
                          asc={sortAsc}
                          onSort={handleSort}
                        />
                        <SortableHead
                          label="Avg duration"
                          field="duration"
                          activeField={sortField}
                          asc={sortAsc}
                          onSort={handleSort}
                        />
                      </tr>
                    </thead>
                    <tbody>
                      {leaderboardRows.map((row) => (
                        <tr key={row.model}>
                          <td>{row.model}</td>
                          <td>{row.runs}</td>
                          <td>
                            <SuccessBar
                              value={row.successRate}
                              label={formatPercent(row.successRate, 1)}
                            />
                          </td>
                          <td>{formatDurationShort(row.avgDuration)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>

          <section className="stats-flex-row">
            <TrendChart
              title="Completed items per day"
              data={completionSeries}
              emptyLabel={historyLoading ? "Loading…" : "No completion history yet"}
              color="#7aa2f7"
            />
            <TrendChart
              title="Daily success rate"
              data={successSeries}
              valueFormatter={(v) => `${v.toFixed(0)}%`}
              emptyLabel={historyLoading ? "Loading…" : "No history yet"}
              color="#9ece6a"
            />
          </section>
        </div>
      </div>
    </div>
  );
}

function buildAgentActivity(stats: SessionStats | null): AgentActivity {
  const segments: AgentSegment[] = [
    { label: "Work", value: stats?.work_agent_runs ?? 0, color: "#7aa2f7" },
    { label: "Gate", value: stats?.gate_agent_runs ?? 0, color: "#f7768e" },
    { label: "Tech Debt", value: stats?.tech_debt_agent_runs ?? 0, color: "#e0af68" },
    { label: "Janitor", value: stats?.janitor_agent_runs ?? 0, color: "#9ece6a" },
    { label: "Backlog", value: stats?.backlog_cleanup_agent_runs ?? 0, color: "#ff9e64" },
    { label: "Cleanup", value: stats?.cleanup_agent_runs ?? 0, color: "#bb9af7" },
    { label: "Beta", value: stats?.beta_tester_agent_runs ?? 0, color: "#2ac3de" },
    { label: "Review", value: stats?.code_review_agent_runs ?? 0, color: "#c0caf5" },
  ].filter((segment) => segment.value > 0);

  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  return { total, segments };
}

function normalizeAgentSegments(agentActivity: AgentActivity): NormalizedAgentSegment[] {
  if (!agentActivity.total) return [];
  let cursor = 0;
  return agentActivity.segments.map((segment) => {
    const width = agentActivity.total ? (segment.value / agentActivity.total) * 100 : 0;
    const normalized = { ...segment, width, start: cursor };
    cursor += width;
    return normalized;
  });
}

function buildCompletionSeries(history: ModelHistoryEntry[]): TrendPoint[] {
  const byDay = aggregateHistory(history);
  if (byDay.length === 0) return [];
  return byDay.map((entry) => ({
    label: entry.dateLabel,
    value: entry.successCount,
  }));
}

function buildSuccessRateSeries(history: ModelHistoryEntry[]): TrendPoint[] {
  const byDay = aggregateHistory(history);
  if (byDay.length === 0) return [];
  return byDay.map((entry) => ({
    label: entry.dateLabel,
    value: entry.decidedCount > 0 ? (entry.successCount / entry.decidedCount) * 100 : 0,
  }));
}

function aggregateHistory(history: ModelHistoryEntry[]) {
  const map = new Map<string, { successCount: number; decidedCount: number }>();
  for (const entry of history) {
    const dateKey = (entry.timestamp ?? "").slice(0, 10) || "unknown";
    const bucket = map.get(dateKey) ?? { successCount: 0, decidedCount: 0 };
    if (entry.gate_passed === true) {
      bucket.successCount += 1;
      bucket.decidedCount += 1;
    } else if (entry.gate_passed === false) {
      bucket.decidedCount += 1;
    }
    map.set(dateKey, bucket);
  }

  const dates = Array.from(map.keys()).sort();
  const trimmed = dates.slice(-14);
  return trimmed.map((date) => ({
    dateLabel: date,
    successCount: map.get(date)?.successCount ?? 0,
    decidedCount: map.get(date)?.decidedCount ?? 0,
  }));
}

function TrendChart({
  title,
  data,
  color,
  valueFormatter,
  emptyLabel,
}: {
  title: string;
  data: TrendPoint[];
  color: string;
  valueFormatter?: (value: number) => string;
  emptyLabel: string;
}) {
  if (!data.length) {
    return (
      <div className="stats-panel-card trend-card">
        <div className="stats-panel-card-header">
          <h3>{title}</h3>
        </div>
        <p className="stats-empty">{emptyLabel}</p>
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.value), 1);
  const points = data.map((point, index) => {
    const x = data.length === 1 ? 50 : (index / (data.length - 1)) * 100;
    const normalized = maxValue === 0 ? 0 : (point.value / maxValue) * 100;
    const y = 100 - normalized;
    return `${x},${y}`;
  });

  return (
    <div className="stats-panel-card trend-card">
      <div className="stats-panel-card-header">
        <h3>{title}</h3>
      </div>
      <div className="trend-chart">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline
            fill="none"
            stroke={color}
            strokeWidth="2"
            points={points.join(" ")}
          />
        </svg>
        <ul className="trend-chart-labels">
          {data.map((point) => (
            <li key={point.label}>
              <span>{point.label}</span>
              <strong>{valueFormatter ? valueFormatter(point.value) : point.value}</strong>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function SortableHead({
  label,
  field,
  activeField,
  asc,
  onSort,
}: {
  label: string;
  field: SortField;
  activeField: SortField;
  asc: boolean;
  onSort: (field: SortField) => void;
}) {
  const isActive = activeField === field;
  return (
    <th>
      <button
        type="button"
        className={`sort-head ${isActive ? "active" : ""}`}
        onClick={() => onSort(field)}
      >
        {label}
        {isActive && <span className="sort-indicator">{asc ? "↑" : "↓"}</span>}
      </button>
    </th>
  );
}

function SuccessBar({ value, label }: { value: number; label: string }) {
  const percent = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="success-bar">
      <svg viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
        <rect className="success-bar-track" x={0} y={0} width={100} height={8} rx={4} ry={4} />
        <rect
          className="success-bar-progress"
          x={0}
          y={0}
          width={percent}
          height={8}
          rx={4}
          ry={4}
        />
      </svg>
      <span className="success-bar-label">{label}</span>
    </div>
  );
}

function gateStatusText(value: boolean | null): string {
  if (value === true) return "Passed gate";
  if (value === false) return "Failed gate";
  return "Pending";
}

function statusClass(value: boolean | null): string {
  if (value === true) return "status-pass";
  if (value === false) return "status-fail";
  return "status-neutral";
}
