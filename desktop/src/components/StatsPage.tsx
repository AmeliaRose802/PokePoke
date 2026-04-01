import { useMemo, useState } from "react";

import { useCopyCompletedItems } from "../hooks/useCopyCompletedItems";
import type { AgentInfo, ConcurrencyTimeline, ModelHistoryEntry, ModelPerformanceSummary, SessionStats } from "../types";
import { buildAgentActivity, normalizeAgentSegments, type NormalizedAgentSegment } from "../utils/agentActivity";
import { getAgentType } from "../utils/agentHelpers";
import { getInProgressItems } from "../utils/inProgressItems";
import {
  buildCompletionSeries,
  buildCompletionTimeSeries,
  buildSuccessRateSeries,
  formatDurationShort,
  formatElapsed,
  formatTokens,
  getAddedCount,
  getCompletedItems,
  getDoneCount,
  getNetDelta,
} from "../utils/stats";
import { CompletedItemCard } from "./CompletedItemCard";
import { CompletionTimeChart } from "./CompletionTimeChart";
import { ConcurrencyChart } from "./ConcurrencyChart";
import { InProgressItemsSection } from "./InProgressItemsSection";
import { ModelTable } from "./ModelTable";
import { TrendChart } from "./TrendChart";

interface StatsPageProps {
  stats: SessionStats | null;
  modelLeaderboard: Record<string, ModelPerformanceSummary>;
  modelHistory: ModelHistoryEntry[];
  historyLoading: boolean;
  historyError: string | null;
  onRefreshHistory: () => void;
  onClose: () => void;
  agents?: AgentInfo[];
  concurrencyTimeline?: ConcurrencyTimeline | null;
}

type SortField = "model" | "runs" | "success" | "duration" | "tokens";

interface AgentTokenSegment {
  label: string;
  tokens: number;
  color: string;
}

export function StatsPage({
  stats,
  modelLeaderboard,
  modelHistory,
  historyLoading,
  historyError,
  onRefreshHistory,
  onClose,
  agents = [],
  concurrencyTimeline,
}: StatsPageProps) {
  const agent = stats?.agent_stats;
  const [completedItems, doneCount] = [getCompletedItems(stats), getDoneCount(stats)];
  const inProgressItems = useMemo(() => getInProgressItems(agents), [agents]);
  const addedCount = getAddedCount(stats);
  const netDelta = getNetDelta(stats);
  const lifetimeAdded = stats?.lifetime_items_created ?? 0;
  const lifetimeDone = stats?.lifetime_items_completed ?? 0;
  const lifetimeNet = lifetimeAdded - lifetimeDone;

  const sessionCards = [
    { label: "Added", value: addedCount, icon: "➕" },
    { label: "Done", value: doneCount, icon: "✅" },
    { label: "Net", value: netDelta > 0 ? `+${netDelta}` : netDelta, icon: "📊" },
    { label: "Retries", value: agent?.retries ?? 0, icon: "🔁" },
    { label: "API Calls", value: agent?.premium_requests ?? 0, icon: "📡" },
    {
      label: "API seconds",
      value: (agent?.api_duration ?? 0) > 0 ? formatDurationShort(agent?.api_duration) : "—",
      icon: "⚡",
    },
    { label: "Tokens", value: formatTokens((agent?.input_tokens ?? 0) + (agent?.output_tokens ?? 0)), icon: "🧮" },
    { label: "Tool Calls", value: agent?.tool_calls ?? 0, icon: "🛠️" },
    { label: "Uptime", value: formatElapsed(stats?.elapsed_time ?? 0), icon: "⏱️" },
  ];
  const agentActivity = buildAgentActivity(stats);
  const normalizedSegments: NormalizedAgentSegment[] = normalizeAgentSegments(agentActivity);
  const [sortField, setSortField] = useState<SortField>("success");
  const [sortAsc, setSortAsc] = useState(false);
  const { copyStatus, copyCompletedItems } = useCopyCompletedItems();

  const handleCopyCompletedItems = () => {
    copyCompletedItems(completedItems, modelHistory);
  };

  const tokensByModel = useMemo(() => {
    const map: Record<string, number> = {};
    for (const entry of modelHistory) {
      const total = (entry.input_tokens ?? 0) + (entry.output_tokens ?? 0);
      map[entry.model] = (map[entry.model] ?? 0) + total;
    }
    return map;
  }, [modelHistory]);

  const leaderboardRows = useMemo(() => {
    const rows = Object.entries(modelLeaderboard ?? {}).map(([model, summary]) => ({
      model,
      runs: summary.total_items_attempted ?? 0,
      successRate: summary.success_rate ?? 0,
      avgDuration: summary.average_duration ?? 0,
      medianDuration: summary.median_duration ?? summary.average_duration ?? 0,
      stddevDuration: summary.stddev_duration ?? 0,
      tokens: tokensByModel[model] ?? 0,
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
        case "tokens":
          comparison = a.tokens - b.tokens;
          break;
        default:
          comparison = a.model.localeCompare(b.model);
      }
      return sortAsc ? comparison : -comparison;
    });

    return sorted;
  }, [modelLeaderboard, tokensByModel, sortField, sortAsc]);

  const agentTokenSegments = useMemo(() => buildTokensByAgentType(agents), [agents]);

  const completionSeries = useMemo(() => buildCompletionSeries(modelHistory), [modelHistory]);
  const successSeries = useMemo(() => buildSuccessRateSeries(modelHistory), [modelHistory]);
  const completionTimeSeries = useMemo(() => buildCompletionTimeSeries(modelHistory), [modelHistory]);

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
                <span className="stats-card-icon">📊</span>
                <div className="stats-card-body">
                  <span className="stats-card-label">Net</span>
                  <span className="stats-card-value">{lifetimeNet > 0 ? `+${lifetimeNet}` : lifetimeNet}</span>
                </div>
              </div>
            </div>
          </section>

          {(completedItems.length > 0 || inProgressItems.length > 0) && (
            <section className="stats-flex-row">
              {inProgressItems.length > 0 && <InProgressItemsSection items={inProgressItems} />}
              {completedItems.length > 0 && (
                <div className="stats-panel-card">
                  <div className="stats-panel-card-header">
                    <h3>
                      Completed this session <span className="stats-panel-subtitle">Gate-passed and merged</span>
                    </h3>
                    <button
                      className={`copy-button ${copyStatus}`}
                      onClick={handleCopyCompletedItems}
                      title="Copy completed items to clipboard"
                      aria-label={
                        copyStatus === "success"
                          ? "Copied to clipboard!"
                          : copyStatus === "error"
                            ? "Failed to copy"
                            : "Copy completed items to clipboard"
                      }
                    >
                      {copyStatus === "success" ? "✅" : copyStatus === "error" ? "❌" : "📋"}
                    </button>
                  </div>
                  <ul className="completed-items-list">
                    {completedItems.map((ci) => (
                      <CompletedItemCard key={ci.id} item={ci} modelHistory={modelHistory} />
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {agentActivity.total > 0 && (
            <section>
              <div className="stats-panel-card">
                <div className="stats-panel-card-header">
                  <h3>Agent activity</h3>
                  <span className="stats-panel-subtitle">Time spent per agent type</span>
                </div>
                <div className="agent-activity-bar">
                  <svg
                    viewBox="0 0 100 10"
                    preserveAspectRatio="none"
                    role="img"
                    aria-label="Agent activity distribution"
                  >
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
              </div>
            </section>
          )}

          {concurrencyTimeline && concurrencyTimeline.lifecycle.length > 0 && (
            <section>
              <ConcurrencyChart data={concurrencyTimeline} />
            </section>
          )}

          {agentTokenSegments.length > 0 && (
            <section>
              <div className="stats-panel-card">
                <div className="stats-panel-card-header">
                  <h3>Tokens per agent</h3>
                  <span className="stats-panel-subtitle">Token usage broken down by agent type this session</span>
                </div>
                <TokensPerAgentChart segments={agentTokenSegments} />
              </div>
            </section>
          )}

          {leaderboardRows.length > 0 && (
            <section>
              <div className="stats-panel-card">
                <div className="stats-panel-card-header">
                  <h3>All-time model performance</h3>
                  <span className="stats-panel-subtitle">Sortable leaderboard with success bars</span>
                </div>
                <ModelTable rows={leaderboardRows} sortField={sortField} sortAsc={sortAsc} onSort={handleSort} />
              </div>
            </section>
          )}

          {(completionSeries.length > 0 || successSeries.length > 0) && (
            <section className="stats-flex-row">
              {completionSeries.length > 0 && (
                <TrendChart title="Completed items per day" data={completionSeries} emptyLabel="" color="#7aa2f7" />
              )}
              {successSeries.length > 0 && (
                <TrendChart
                  title="Daily success rate"
                  data={successSeries}
                  valueFormatter={(v) => `${v.toFixed(0)}%`}
                  emptyLabel=""
                  color="#9ece6a"
                />
              )}
            </section>
          )}

          {Object.values(completionTimeSeries).some((s) => s.length > 0) && (
            <section>
              <div className="stats-panel-card">
                <div className="stats-panel-card-header">
                  <h3>Average completion time by tag</h3>
                  <span className="stats-panel-subtitle">Trends in item resolution time over last 14 days</span>
                </div>
                <CompletionTimeChart
                  data={completionTimeSeries}
                  emptyLabel={historyLoading ? "Loading…" : "No completion time history yet"}
                />
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

const AGENT_TOKEN_DEFS: { key: string; label: string; color: string }[] = [
  { key: "work", label: "Work", color: "#7aa2f7" },
  { key: "gate", label: "Gate", color: "#f7768e" },
  { key: "tech_debt", label: "Tech Debt", color: "#e0af68" },
  { key: "janitor", label: "Janitor", color: "#9ece6a" },
  { key: "backlog_cleanup", label: "Backlog", color: "#ff9e64" },
  { key: "cleanup", label: "Cleanup", color: "#bb9af7" },
  { key: "beta_tester", label: "Beta", color: "#2ac3de" },
  { key: "code_review", label: "Review", color: "#c0caf5" },
];

const AGENT_TOKEN_KEYS = new Set(AGENT_TOKEN_DEFS.map((def) => def.key));
const AGENT_TYPE_TOKEN_ALIASES: Record<string, string> = {
  beta_test: "beta_tester",
  beta_test_agent: "beta_tester",
  beta_tester_agent: "beta_tester",
  cleanup_agent: "cleanup",
  merge_conflict: "cleanup",
  merge_conflict_cleanup: "cleanup",
  code_conflict: "cleanup",
  code_conflict_agent: "cleanup",
  janitor_agent: "janitor",
  maintenance_janitor: "janitor",
  techdebt: "tech_debt",
  tech_debt_agent: "tech_debt",
  maintenance_tech_debt: "tech_debt",
  backlog_cleanup_agent: "backlog_cleanup",
};

function normalizeAgentTypeKey(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return normalized || null;
}

function resolveAgentType(agent: AgentInfo): string {
  const candidates = [agent.agent_type, agent.base_agent_id, agent.agent_id, agent.name, getAgentType(agent)];

  for (const candidate of candidates) {
    const normalized = normalizeAgentTypeKey(candidate);
    if (!normalized) continue;
    const aliased = AGENT_TYPE_TOKEN_ALIASES[normalized] ?? normalized;
    if (AGENT_TOKEN_KEYS.has(aliased)) {
      return aliased;
    }
  }

  return "other";
}

function buildTokensByAgentType(agents: AgentInfo[]): AgentTokenSegment[] {
  const totals = new Map<string, number>();
  for (const agent of agents) {
    const type = resolveAgentType(agent);
    const total = (agent.input_tokens ?? 0) + (agent.output_tokens ?? 0);
    if (total > 0) {
      totals.set(type, (totals.get(type) ?? 0) + total);
    }
  }

  const result: AgentTokenSegment[] = [];
  for (const def of AGENT_TOKEN_DEFS) {
    const tokens = totals.get(def.key);
    if (tokens !== undefined && tokens > 0) {
      result.push({ label: def.label, tokens, color: def.color });
      totals.delete(def.key);
    }
  }
  // Append any agent types not in the known list
  for (const [key, tokens] of totals.entries()) {
    if (tokens > 0) {
      result.push({ label: key, tokens, color: "#7dcfff" });
    }
  }

  return result.sort((a, b) => b.tokens - a.tokens);
}

function TokensPerAgentChart({ segments }: { segments: AgentTokenSegment[] }) {
  const maxTokens = Math.max(...segments.map((s) => s.tokens), 1);
  return (
    <div className="tokens-per-agent-chart" role="list">
      {segments.map((segment) => {
        const barWidth = (segment.tokens / maxTokens) * 100;
        return (
          <div key={segment.label} className="tokens-per-agent-row" role="listitem">
            <span className="tokens-per-agent-label">{segment.label}</span>
            <div className="tokens-per-agent-bar-container">
              <svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
                <rect x={0} y={0} width={barWidth} height={10} fill={segment.color} rx={4} ry={4}>
                  <title>{`${segment.label}: ${formatTokens(segment.tokens)} tokens`}</title>
                </rect>
              </svg>
            </div>
            <span className="tokens-per-agent-value">{formatTokens(segment.tokens)}</span>
          </div>
        );
      })}
    </div>
  );
}
