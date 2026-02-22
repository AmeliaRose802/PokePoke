import { useMemo, useState } from "react";

import type {
  ModelHistoryEntry,
  ModelPerformanceSummary,
  SessionStats,
} from "../types";
import {
  buildCompletionTimeSeries,
  buildItemTypeBreakdown,
  formatDurationShort,
  formatElapsed,
  formatPercent,
  formatTokens,
  getAddedCount,
  getCompletedItems,
  getDoneCount,
  getNetDelta,
  inferCurrentModel,
} from "../utils/stats";
import { CompletionTimeChart } from "./CompletionTimeChart";
import { ModelTable } from "./ModelTable";
import { TrendChart, type TrendPoint } from "./TrendChart";

interface StatsPageProps {
  stats: SessionStats | null;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  activeAgentModel?: string | null;
  modelHistory: ModelHistoryEntry[];
  historyLoading: boolean;
  historyError: string | null;
  onRefreshHistory: () => void;
  onClose: () => void;
}

type SortField = "model" | "runs" | "success" | "duration" | "api";
interface AgentSegment { label: string; value: number; color: string; }
interface AgentActivity { total: number; segments: AgentSegment[]; }
interface NormalizedAgentSegment extends AgentSegment { start: number; width: number; }

export function StatsPage({
  stats,
  modelLeaderboard,
  activeAgentModel,
  modelHistory,
  historyLoading,
  historyError,
  onRefreshHistory,
  onClose,
}: StatsPageProps) {
  const agent = stats?.agent_stats;
  const [completedItems, doneCount] = [getCompletedItems(stats), getDoneCount(stats)];
  const addedCount = getAddedCount(stats);
  const netDelta = getNetDelta(stats);
  const lifetimeAdded = stats?.lifetime_items_created ?? 0;
  const lifetimeDone = stats?.lifetime_items_completed ?? 0;
  const lifetimeNet = lifetimeAdded - lifetimeDone;

  const sessionCards = [
    { label: "Added", value: addedCount, icon: "➕" },
    { label: "Done", value: doneCount, icon: "✅" },
    { label: "Net", value: netDelta > 0 ? `+${netDelta}` : netDelta, icon: "🌿" },
    { label: "Retries", value: agent?.retries ?? 0, icon: "🔁" },
    { label: "API Calls", value: agent?.premium_requests ?? 0, icon: "📡" },
    { label: "API seconds", value: (agent?.api_duration ?? 0) > 0 ? formatDurationShort(agent?.api_duration) : "—", icon: "⚡" },
    { label: "Tokens", value: formatTokens((agent?.input_tokens ?? 0) + (agent?.output_tokens ?? 0)), icon: "🧮" },
    { label: "Tool Calls", value: agent?.tool_calls ?? 0, icon: "🛠️" },
    { label: "Uptime", value: formatElapsed(stats?.elapsed_time ?? 0), icon: "⏱️" },
  ];
  const agentActivity = buildAgentActivity(stats);
  const normalizedSegments = normalizeAgentSegments(agentActivity);
  const currentModel = inferCurrentModel(stats, modelLeaderboard, activeAgentModel);

  const [sortField, setSortField] = useState<SortField>("success");
  const [sortAsc, setSortAsc] = useState(false);

  const leaderboardRows = useMemo(() => {
    const rows = Object.entries(modelLeaderboard ?? {}).map(([model, summary]) => ({
      model,
      runs: summary.total_items_attempted ?? 0,
      successRate: summary.success_rate ?? 0,
      avgDuration: summary.average_duration ?? 0,
      medianDuration: summary.median_duration ?? summary.average_duration ?? 0,
      stddevDuration: summary.stddev_duration ?? 0,
      avgApiSeconds: summary.average_api_seconds ?? 0,
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
          comparison = a.medianDuration - b.medianDuration;
          break;
        case "api":
          comparison = a.avgApiSeconds - b.avgApiSeconds;
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
  const completionTimeSeries = useMemo(() => buildCompletionTimeSeries(modelHistory), [modelHistory]);

  const itemTypeBreakdown = useMemo(
    () => buildItemTypeBreakdown(completedItems, modelHistory),
    [completedItems, modelHistory]
  );
  const itemTypeTotal = itemTypeBreakdown.reduce((sum, t) => sum + t.count, 0);
  const normalizedItemTypes = useMemo(() => {
    if (!itemTypeTotal) return [];
    let cursor = 0;
    return itemTypeBreakdown.map((entry) => {
      const width = (entry.count / itemTypeTotal) * 100;
      const result = { ...entry, start: cursor, width };
      cursor += width;
      return result;
    });
  }, [itemTypeBreakdown, itemTypeTotal]);

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

          <section>
            <h3>Lifetime beads throughput</h3>
            <div className="stats-card-grid">
              <div className="stats-card">
                <span className="stats-card-icon">➕</span>
                <div className="stats-card-body">
                  <span className="stats-card-label">Added</span>
                  <span className="stats-card-value">{lifetimeAdded}</span>
                </div>
              </div>
              <div className="stats-card">
                <span className="stats-card-icon">✅</span>
                <div className="stats-card-body">
                  <span className="stats-card-label">Done</span>
                  <span className="stats-card-value">{lifetimeDone}</span>
                </div>
              </div>
              <div className="stats-card">
                <span className="stats-card-icon">🌿</span>
                <div className="stats-card-body">
                  <span className="stats-card-label">Net</span>
                  <span className="stats-card-value">{lifetimeNet > 0 ? `+${lifetimeNet}` : lifetimeNet}</span>
                </div>
              </div>
            </div>
          </section>

          <section>
            <div className="stats-panel-card">
              <div className="stats-panel-card-header">
                <h3>Item type breakdown</h3>
                <span className="stats-panel-subtitle">Distribution by beads issue type</span>
              </div>
              {normalizedItemTypes.length > 0 ? (
                <>
                  <div className="agent-activity-bar">
                    <svg viewBox="0 0 100 10" preserveAspectRatio="none" role="img" aria-label="Item type distribution">
                      {normalizedItemTypes.map((segment) => (
                        <rect
                          key={segment.type}
                          x={segment.start}
                          y={0}
                          width={segment.width}
                          height={10}
                          fill={segment.color}
                        >
                          <title>{`${segment.type}: ${segment.count} (${segment.width.toFixed(1)}%)`}</title>
                        </rect>
                      ))}
                    </svg>
                  </div>
                  <div className="agent-activity-legend">
                    {normalizedItemTypes.map((segment) => (
                      <span key={segment.type} className="agent-activity-pill">
                        <span className="agent-legend-dot" aria-hidden="true">
                          <svg viewBox="0 0 8 8" preserveAspectRatio="none">
                            <circle cx="4" cy="4" r="4" fill={segment.color} />
                          </svg>
                        </span>
                        {segment.type}: {segment.count}
                      </span>
                    ))}
                  </div>
                </>
              ) : (
                <p className="stats-empty">No items with type data yet.</p>
              )}
            </div>
          </section>

          <section>
            <div className="stats-panel-card">
              <h3>Completed this session <span className="stats-panel-subtitle">Gate-passed and merged</span></h3>
              {completedItems.length > 0 ? (
                <ul className="completed-items-list">
                  {completedItems.map((ci) => (
                    <li key={ci.id}><strong>{ci.id}</strong>{ci.title ? ` — ${ci.title}` : ""}</li>
                  ))}
                </ul>
              ) : <p className="stats-empty">No completed items yet.</p>}
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
                          <title>{`${segment.label}: ${segment.width.toFixed(1)}%`}</title>
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
                        {segment.label}: {segment.width.toFixed(1)}%
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
              <ModelTable
                rows={leaderboardRows}
                sortField={sortField}
                sortAsc={sortAsc}
                onSort={handleSort}
              />
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

          <section>
            <div className="stats-panel-card">
              <div className="stats-panel-card-header">
                <h3>Average completion time by type</h3>
                <span className="stats-panel-subtitle">Trends in item resolution time over last 14 days</span>
              </div>
              <CompletionTimeChart
                data={completionTimeSeries}
                emptyLabel={historyLoading ? "Loading…" : "No completion time history yet"}
              />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function buildAgentActivity(stats: SessionStats | null): AgentActivity {
  const elapsed = stats?.agent_type_elapsed_seconds ?? {};

  // Map from internal key → display label and color
  const definitions: { key: string; label: string; color: string }[] = [
    { key: "work",             label: "Work",      color: "#7aa2f7" },
    { key: "gate",             label: "Gate",      color: "#f7768e" },
    { key: "tech_debt",        label: "Tech Debt", color: "#e0af68" },
    { key: "janitor",          label: "Janitor",   color: "#9ece6a" },
    { key: "backlog_cleanup",  label: "Backlog",   color: "#ff9e64" },
    { key: "cleanup",          label: "Cleanup",   color: "#bb9af7" },
    { key: "beta_tester",      label: "Beta",      color: "#2ac3de" },
    { key: "code_review",      label: "Review",    color: "#c0caf5" },
  ];

  const segments: AgentSegment[] = definitions
    .map(({ key, label, color }) => ({ label, value: elapsed[key] ?? 0, color }))
    .filter((segment) => segment.value > 0);

  // Fall back to counts when no elapsed time is recorded (e.g. legacy data)
  if (segments.length === 0) {
    return buildAgentActivityFromCounts(stats);
  }

  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  return { total, segments };
}

function buildAgentActivityFromCounts(stats: SessionStats | null): AgentActivity {
  const segments: AgentSegment[] = [
    { label: "Work",      value: stats?.work_agent_runs ?? 0,           color: "#7aa2f7" },
    { label: "Gate",      value: stats?.gate_agent_runs ?? 0,           color: "#f7768e" },
    { label: "Tech Debt", value: stats?.tech_debt_agent_runs ?? 0,      color: "#e0af68" },
    { label: "Janitor",   value: stats?.janitor_agent_runs ?? 0,        color: "#9ece6a" },
    { label: "Backlog",   value: stats?.backlog_cleanup_agent_runs ?? 0, color: "#ff9e64" },
    { label: "Cleanup",   value: stats?.cleanup_agent_runs ?? 0,        color: "#bb9af7" },
    { label: "Beta",      value: stats?.beta_tester_agent_runs ?? 0,    color: "#2ac3de" },
    { label: "Review",    value: stats?.code_review_agent_runs ?? 0,    color: "#c0caf5" },
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

const gateStatusText = (v: boolean | null) =>
  v === true ? "Passed gate" : v === false ? "Failed gate" : "Pending";
const statusClass = (v: boolean | null) =>
  v === true ? "status-pass" : v === false ? "status-fail" : "status-neutral";
