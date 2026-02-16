import type {
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

export function formatDurationShort(seconds: number | undefined): string {
  if (!Number.isFinite(seconds ?? 0)) return "0s";
  const value = Math.max(0, seconds ?? 0);
  if (value < 60) return `${value.toFixed(0)}s`;
  if (value < 3600) return `${(value / 60).toFixed(1)}m`;
  return `${(value / 3600).toFixed(1)}h`;
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
  leaderboard: Record<string, ModelPerformanceSummary>
): CurrentModelInfo {
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
