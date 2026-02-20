import type {
  CompletedItem,
  CreatedItem,
  ModelHistoryEntry,
  ModelPerformanceSummary,
  SessionStats,
} from "../types";

export function formatTokens(count: number | undefined): string {
  if (!Number.isFinite(count ?? 0)) return "0";
  const value = count ?? 0;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatTotalTokens(stats: SessionStats | null): string {
  if (!stats?.agent_stats) return "0";
  const inputTokens = stats.agent_stats.input_tokens || 0;
  const outputTokens = stats.agent_stats.output_tokens || 0;
  const totalTokens = inputTokens + outputTokens;
  return formatTokens(totalTokens);
}

export function formatDurationShort(seconds: number | undefined): string {
  if (!Number.isFinite(seconds ?? 0)) return "0s";
  const value = Math.max(0, seconds ?? 0);
  if (value < 60) return `${value.toFixed(0)}s`;
  if (value < 3600) return `${(value / 60).toFixed(1)}m`;
  return `${(value / 3600).toFixed(1)}h`;
}

export function formatDurationWithSpread(
  median: number | undefined,
  stddev: number | undefined
): string {
  const med = formatDurationShort(median);
  if (!Number.isFinite(stddev ?? 0) || (stddev ?? 0) === 0) return med;
  const dev = formatDurationShort(stddev);
  return `${med} ±${dev}`;
}

export function formatElapsed(seconds: number | undefined): string {
  const value = Math.max(0, seconds ?? 0);
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = Math.floor(value % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(
    s
  ).padStart(2, "0")}`;
}

export function formatPercent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export interface CurrentModelInfo {
  model: string | null;
  gatePassed: boolean | null;
  successRate: number | null;
}

export function inferCurrentModel(
  stats: SessionStats | null,
  leaderboard: Record<string, ModelPerformanceSummary>,
  activeAgentModel?: string | null
): CurrentModelInfo {
  const normalizedActive = activeAgentModel?.trim();
  if (normalizedActive) {
    const successRate = leaderboard[normalizedActive]?.success_rate ?? null;
    return { model: normalizedActive, gatePassed: null, successRate };
  }

  const completions = stats?.model_completions ?? [];
  const latest = completions[completions.length - 1];
  if (latest) {
    const successRate = leaderboard[latest.model]?.success_rate ?? null;
    return {
      model: latest.model,
      gatePassed: latest.gate_passed,
      successRate,
    };
  }

  const leaderboardEntries = Object.entries(leaderboard);
  if (leaderboardEntries.length > 0) {
    const [model, summary] = leaderboardEntries.sort(
      (a, b) => (b[1].success_rate ?? 0) - (a[1].success_rate ?? 0)
    )[0];
    return {
      model,
      gatePassed: null,
      successRate: summary?.success_rate ?? null,
    };
  }

  return { model: null, gatePassed: null, successRate: null };
}

export function getCompletedItems(stats: SessionStats | null): CompletedItem[] {
  const items = stats?.completed_items ?? [];
  const seen = new Set<string>();
  const deduped: CompletedItem[] = [];

  for (const item of items) {
    const id = item.id?.trim();
    if (!id) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    deduped.push({ ...item, id });
  }

  return deduped;
}

export function getDoneCount(stats: SessionStats | null): number {
  const completed = getCompletedItems(stats);
  if (completed.length > 0) return completed.length;
  return stats?.items_completed ?? 0;
}

export interface AgentRunCounts {
  work: number;
  cleanup: number; 
  other: number;
}

export function getAgentRunCounts(stats: SessionStats | null): AgentRunCounts {
  if (!stats) return { work: 0, cleanup: 0, other: 0 };

  // Work: productive development work
  const work = (stats.work_agent_runs ?? 0);

  // Cleanup: maintenance and cleanup activities  
  const cleanup = 
    (stats.cleanup_agent_runs ?? 0) +
    (stats.janitor_agent_runs ?? 0) +
    (stats.backlog_cleanup_agent_runs ?? 0) +
    (stats.worktree_cleanup_agent_runs ?? 0);

  // Other: specialized tasks like gates, reviews, etc.
  const other =
    (stats.gate_agent_runs ?? 0) +
    (stats.tech_debt_agent_runs ?? 0) +
    (stats.beta_tester_agent_runs ?? 0) +
    (stats.code_review_agent_runs ?? 0);

  return { work, cleanup, other };
}

export function formatAgentRuns(counts: AgentRunCounts): string {
  const parts: string[] = [];
  
  if (counts.work > 0) {
    parts.push(`Work ${counts.work}`);
  }
  if (counts.cleanup > 0) {
    parts.push(`Cleanup ${counts.cleanup}`);
  }
  if (counts.other > 0) {
    parts.push(`Other ${counts.other}`);
  }
  
  return parts.length > 0 ? parts.join(" · ") : "—";
}

export function getCreatedItems(stats: SessionStats | null): CreatedItem[] {
  const items = stats?.created_items ?? [];
  const seen = new Set<string>();
  const deduped: CreatedItem[] = [];

  for (const item of items) {
    const id = item.id?.trim();
    if (!id) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    deduped.push({ ...item, id });
  }

  return deduped;
}

export function getAddedCount(stats: SessionStats | null): number {
  const created = getCreatedItems(stats);
  if (created.length > 0) return created.length;
  return stats?.items_created ?? 0;
}

export function getNetDelta(stats: SessionStats | null): number {
  if (typeof stats?.net_items_delta === "number") return stats.net_items_delta;
  return getAddedCount(stats) - getDoneCount(stats);
}

/**
 * Calculate average completion time by item type with rolling averages
 * Groups historical entries by item type and computes mean duration
 */
export function buildCompletionTimeByType(
  history: ModelHistoryEntry[]
): Record<string, number> {
  const byType = new Map<string, number[]>();

  for (const entry of history) {
    const type = entry.item_type || "unknown";
    const durations = byType.get(type) ?? [];
    durations.push(entry.duration_seconds);
    byType.set(type, durations);
  }

  const result: Record<string, number> = {};
  for (const [type, durations] of byType.entries()) {
    const avg = durations.reduce((a, b) => a + b, 0) / durations.length;
    result[type] = avg;
  }
  return result;
}

/**
 * Build time series data for completion time trends by item type
 * Returns data grouped by type for multi-series chart
 */
export function buildCompletionTimeSeries(
  history: ModelHistoryEntry[]
): Record<
  string,
  Array<{ label: string; value: number }>
> {
  const byTypeAndDay = new Map<
    string,
    Map<string, { durations: number[]; count: number }>
  >();

  for (const entry of history) {
    const type = entry.item_type || "unknown";
    const dateKey = (entry.timestamp ?? "").slice(0, 10) || "unknown";

    if (!byTypeAndDay.has(type)) {
      byTypeAndDay.set(type, new Map());
    }

    const typeMap = byTypeAndDay.get(type)!;
    const bucket = typeMap.get(dateKey) ?? { durations: [], count: 0 };
    bucket.durations.push(entry.duration_seconds);
    bucket.count += 1;
    typeMap.set(dateKey, bucket);
  }

  const result: Record<string, Array<{ label: string; value: number }>> = {};

  for (const [type, typeMap] of byTypeAndDay.entries()) {
    const dates = Array.from(typeMap.keys()).sort();
    const trimmed = dates.slice(-14); // Last 14 days

    result[type] = trimmed.map((date) => {
      const bucket = typeMap.get(date)!;
      const avg =
        bucket.durations.length > 0
          ? bucket.durations.reduce((a, b) => a + b, 0) / bucket.durations.length
          : 0;
      return { label: date, value: avg };
    });
  }

  return result;
}
