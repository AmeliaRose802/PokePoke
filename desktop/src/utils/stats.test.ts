import { describe, expect, it } from "vitest";

import type { AgentInfo, ModelHistoryEntry, ModelPerformanceSummary, SessionStats } from "../types";
import {
  aggregateHistory,
  buildCompletionSeries,
  buildSuccessRateSeries,
  combineRunCounts,
  formatAgentRuns,
  formatDurationShort,
  formatDurationWithSpread,
  getActiveRunCounts,
  getAgentRunCounts,
  getCompletedItems,
  getDoneCount,
  inferCurrentModel,
} from "./stats";

describe("stats helpers", () => {
  describe("formatDurationShort", () => {
    it("formats seconds with 2 decimal places, removing trailing zeros", () => {
      // The bug example: 51.768338680267334s should become ~51.77s
      expect(formatDurationShort(51.768338680267334)).toBe("51.77s");
      expect(formatDurationShort(12.45)).toBe("12.45s");
      expect(formatDurationShort(5.001)).toBe("5s"); // 5.00 -> remove zeros -> 5
      expect(formatDurationShort(5.5)).toBe("5.5s");
    });

    it("removes trailing zeros from seconds", () => {
      expect(formatDurationShort(51.7)).toBe("51.7s");
      expect(formatDurationShort(10)).toBe("10s");
      expect(formatDurationShort(5.1)).toBe("5.1s");
    });

    it("formats minutes with 1 decimal place minimum", () => {
      expect(formatDurationShort(120)).toBe("2.0m");
      expect(formatDurationShort(150)).toBe("2.5m");
      expect(formatDurationShort(130)).toBe("2.2m");
      expect(formatDurationShort(125)).toBe("2.1m");
    });

    it("removes trailing zeros from minutes (except one decimal when < 10m)", () => {
      expect(formatDurationShort(600)).toBe("10m"); // 10m exactly shows without decimal
      expect(formatDurationShort(630)).toBe("10.5m");
      expect(formatDurationShort(120)).toBe("2.0m"); // < 10m shows with decimal
    });

    it("formats hours with h m format", () => {
      expect(formatDurationShort(3600)).toBe("1h 0m");
      expect(formatDurationShort(3660)).toBe("1h 1m");
      expect(formatDurationShort(5400)).toBe("1h 30m");
      expect(formatDurationShort(7200)).toBe("2h 0m");
    });

    it("handles edge cases", () => {
      expect(formatDurationShort(0)).toBe("0s");
      expect(formatDurationShort(undefined)).toBe("0s");
      expect(formatDurationShort(NaN)).toBe("0s");
    });
  });

  describe("formatDurationWithSpread", () => {
    it("shows median ±stddev when stddev is non-zero", () => {
      // 2610s = 43.5m, 720s = 12.0m
      expect(formatDurationWithSpread(2610, 720)).toBe("43.5m ±12m");
    });

    it("shows only median when stddev is zero", () => {
      expect(formatDurationWithSpread(59, 0)).toBe("59s");
    });

    it("shows only median when stddev is undefined", () => {
      expect(formatDurationWithSpread(120, undefined)).toBe("2.0m");
    });

    it("handles seconds-range values", () => {
      expect(formatDurationWithSpread(30, 5)).toBe("30s ±5s");
    });

    it("handles hours-range values", () => {
      expect(formatDurationWithSpread(7200, 3600)).toBe("2h 0m ±1h 0m");
    });

    it("handles undefined median", () => {
      expect(formatDurationWithSpread(undefined, 10)).toBe("0s ±10s");
    });
  });

  describe("getCompletedItems", () => {
    it("dedupes by id and ignores missing ids", () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        completed_items: [
          { id: "A", title: "First" },
          { id: "A", title: "Duplicate" },
          { id: "  B  ", status: "done" },
          { id: "   " },
        ],
      };

      const result = getCompletedItems(stats);

      expect(result).toHaveLength(2);
      expect(result.map((item) => item.id)).toEqual(["A", "B"]);
    });
  });

  describe("getDoneCount", () => {
    it("prioritizes items_completed counter over array length", () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        completed_items: [{ id: "X" }, { id: "Y" }, { id: "Y" }],
        items_completed: 10,
      };

      // Should return 10 (counter), not 2 (deduplicated array length)
      expect(getDoneCount(stats)).toBe(10);
    });

    it("falls back to array length when counter is missing or zero", () => {
      const withEmptyCounter: SessionStats = {
        elapsed_time: 0,
        completed_items: [{ id: "A" }, { id: "B" }],
        items_completed: 0,
      };

      const withoutCounter: SessionStats = {
        elapsed_time: 0,
        completed_items: [{ id: "X" }, { id: "Y" }, { id: "Y" }],
      };

      const withEmptyArray: SessionStats = {
        elapsed_time: 0,
        completed_items: [],
        items_completed: 5,
      };

      expect(getDoneCount(withEmptyCounter)).toBe(2);
      expect(getDoneCount(withoutCounter)).toBe(2); // deduplicated
      expect(getDoneCount(withEmptyArray)).toBe(5);
    });

    it("returns zero when both counter and array are missing", () => {
      const stats: SessionStats = {
        elapsed_time: 0,
      };

      expect(getDoneCount(stats)).toBe(0);
    });
  });

  describe("inferCurrentModel", () => {
    const leaderboard: Record<string, ModelPerformanceSummary> = {
      "gemini-3-pro": { success_rate: 0.9 } as ModelPerformanceSummary,
      "gpt-5.1": { success_rate: 0.75 } as ModelPerformanceSummary,
    };

    it("prefers the live active agent model when provided", () => {
      const stats: SessionStats = { elapsed_time: 0 };

      const result = inferCurrentModel(stats, leaderboard, "gpt-5.1");

      expect(result).toEqual({
        model: "gpt-5.1",
        gatePassed: null,
        successRate: 0.75,
      });
    });

    it("falls back to latest completion when no active agent model is provided", () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        model_completions: [
          {
            item_id: "AA7Y",
            model: "gemini-3-pro",
            duration_seconds: 123,
            gate_passed: true,
            input_tokens: 1000,
            output_tokens: 500,
            agent_turns: 2,
            cost: 0.05,
            retry_attempts: 0,
            api_duration: null,
            lines_added: null,
            lines_removed: null,
          },
        ],
      };

      const result = inferCurrentModel(stats, leaderboard);

      expect(result).toEqual({
        model: "gemini-3-pro",
        gatePassed: true,
        successRate: 0.9,
      });
    });
  });

  function makeEntry(overrides: Partial<ModelHistoryEntry> = {}): ModelHistoryEntry {
    return {
      item_id: "test-1",
      model: "test-model",
      duration_seconds: 100,
      gate_passed: null,
      input_tokens: 0,
      output_tokens: 0,
      agent_turns: 1,
      cost: 0,
      retry_attempts: 0,
      api_duration: null,
      lines_added: null,
      lines_removed: null,
      timestamp: "2026-02-20T10:00:00+00:00",
      ...overrides,
    };
  }

  describe("aggregateHistory", () => {
    it("counts entries with success=true as completed", () => {
      const history = [
        makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", success: true, gate_passed: true }),
        makeEntry({ timestamp: "2026-02-20T11:00:00+00:00", success: true, gate_passed: true }),
        makeEntry({ timestamp: "2026-02-20T12:00:00+00:00", success: false, gate_passed: false }),
      ];
      const result = aggregateHistory(history);
      expect(result).toHaveLength(1);
      expect(result[0].successCount).toBe(2);
      expect(result[0].decidedCount).toBe(3);
    });

    it("uses success field even when gate_passed is null", () => {
      const history = [
        makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", success: true, gate_passed: null }),
        makeEntry({ timestamp: "2026-02-20T11:00:00+00:00", success: true, gate_passed: null }),
      ];
      const result = aggregateHistory(history);
      expect(result[0].successCount).toBe(2);
      expect(result[0].decidedCount).toBe(2);
    });

    it("falls back to gate_passed when success is undefined", () => {
      const history = [
        makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", gate_passed: true }),
        makeEntry({ timestamp: "2026-02-20T11:00:00+00:00", gate_passed: false }),
      ];
      const result = aggregateHistory(history);
      expect(result[0].successCount).toBe(1);
      expect(result[0].decidedCount).toBe(2);
    });

    it("groups by date across multiple days", () => {
      const history = [
        makeEntry({ timestamp: "2026-02-19T10:00:00+00:00", success: true }),
        makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", success: true }),
        makeEntry({ timestamp: "2026-02-20T11:00:00+00:00", success: false }),
      ];
      const result = aggregateHistory(history);
      expect(result).toHaveLength(2);
      expect(result[0].dateLabel).toBe("2026-02-19");
      expect(result[0].successCount).toBe(1);
      expect(result[1].dateLabel).toBe("2026-02-20");
      expect(result[1].successCount).toBe(1);
      expect(result[1].decidedCount).toBe(2);
    });

    it("returns empty array for empty history", () => {
      expect(aggregateHistory([])).toHaveLength(0);
    });
  });

  describe("buildCompletionSeries", () => {
    it("returns success counts per day", () => {
      const history = [
        makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", success: true }),
        makeEntry({ timestamp: "2026-02-20T11:00:00+00:00", success: true }),
        makeEntry({ timestamp: "2026-02-21T10:00:00+00:00", success: false }),
      ];
      const series = buildCompletionSeries(history);
      expect(series).toHaveLength(2);
      expect(series[0]).toEqual({ label: "2026-02-20", value: 2 });
      expect(series[1]).toEqual({ label: "2026-02-21", value: 0 });
    });

    it("returns empty array for empty history", () => {
      expect(buildCompletionSeries([])).toHaveLength(0);
    });
  });

  describe("buildSuccessRateSeries", () => {
    it("calculates success percentage per day", () => {
      const history = [
        makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", success: true }),
        makeEntry({ timestamp: "2026-02-20T11:00:00+00:00", success: false }),
      ];
      const series = buildSuccessRateSeries(history);
      expect(series).toHaveLength(1);
      expect(series[0].value).toBe(50);
    });

    it("returns 0% when no decided items exist", () => {
      const history = [makeEntry({ timestamp: "2026-02-20T10:00:00+00:00", gate_passed: null })];
      const series = buildSuccessRateSeries(history);
      expect(series).toHaveLength(1);
      expect(series[0].value).toBe(0);
    });

    it("returns empty array for empty history", () => {
      expect(buildSuccessRateSeries([])).toHaveLength(0);
    });
  });

  describe("getAgentRunCounts", () => {
    it("returns zeros for null stats", () => {
      expect(getAgentRunCounts(null)).toEqual({ work: 0, cleanup: 0, other: 0 });
    });

    it("counts work runs from stats", () => {
      const stats = { work_agent_runs: 5 } as SessionStats;
      expect(getAgentRunCounts(stats)).toEqual({ work: 5, cleanup: 0, other: 0 });
    });

    it("counts cleanup runs from stats", () => {
      const stats = {
        cleanup_agent_runs: 2,
        janitor_agent_runs: 1,
        backlog_cleanup_agent_runs: 3,
        worktree_cleanup_agent_runs: 1,
      } as SessionStats;
      expect(getAgentRunCounts(stats)).toEqual({ work: 0, cleanup: 7, other: 0 });
    });

    it("counts other runs from stats", () => {
      const stats = {
        gate_agent_runs: 4,
        tech_debt_agent_runs: 1,
        beta_tester_agent_runs: 2,
        code_review_agent_runs: 1,
      } as SessionStats;
      expect(getAgentRunCounts(stats)).toEqual({ work: 0, cleanup: 0, other: 8 });
    });
  });

  describe("getActiveRunCounts", () => {
    function makeAgent(overrides: Partial<AgentInfo>): AgentInfo {
      return {
        agent_id: "test",
        name: "test",
        iteration: 1,
        status: "running",
        recent_logs: [],
        ...overrides,
      };
    }

    it("returns zeros for empty agents array", () => {
      expect(getActiveRunCounts([])).toEqual({ work: 0, cleanup: 0, other: 0 });
    });

    it("counts only running agents", () => {
      const agents = [
        makeAgent({ agent_id: "a1", agent_type: "work", status: "running" }),
        makeAgent({ agent_id: "a2", agent_type: "work", status: "success" }),
        makeAgent({ agent_id: "a3", agent_type: "work", status: "failed" }),
      ];
      expect(getActiveRunCounts(agents)).toEqual({ work: 1, cleanup: 0, other: 0 });
    });

    it("categorizes running agents by type", () => {
      const agents = [
        makeAgent({ agent_id: "w1", agent_type: "work", status: "running" }),
        makeAgent({ agent_id: "c1", agent_type: "cleanup", status: "running" }),
        makeAgent({ agent_id: "j1", agent_type: "janitor", status: "running" }),
        makeAgent({ agent_id: "g1", agent_type: "gate", status: "running" }),
        makeAgent({ agent_id: "t1", agent_type: "tech_debt", status: "running" }),
      ];
      expect(getActiveRunCounts(agents)).toEqual({ work: 1, cleanup: 2, other: 2 });
    });

    it("treats agents with no agent_type as work", () => {
      const agents = [
        makeAgent({ agent_id: "w1", agent_type: null, status: "running" }),
        makeAgent({ agent_id: "w2", agent_type: undefined, status: "running" }),
      ];
      expect(getActiveRunCounts(agents)).toEqual({ work: 2, cleanup: 0, other: 0 });
    });

    it("categorizes all cleanup types correctly", () => {
      const agents = [
        makeAgent({ agent_id: "c1", agent_type: "cleanup", status: "running" }),
        makeAgent({ agent_id: "c2", agent_type: "janitor", status: "running" }),
        makeAgent({ agent_id: "c3", agent_type: "backlog_cleanup", status: "running" }),
        makeAgent({ agent_id: "c4", agent_type: "worktree_cleanup", status: "running" }),
      ];
      expect(getActiveRunCounts(agents)).toEqual({ work: 0, cleanup: 4, other: 0 });
    });

    it("categorizes all other types correctly", () => {
      const agents = [
        makeAgent({ agent_id: "o1", agent_type: "gate", status: "running" }),
        makeAgent({ agent_id: "o2", agent_type: "tech_debt", status: "running" }),
        makeAgent({ agent_id: "o3", agent_type: "beta_tester", status: "running" }),
        makeAgent({ agent_id: "o4", agent_type: "code_review", status: "running" }),
      ];
      expect(getActiveRunCounts(agents)).toEqual({ work: 0, cleanup: 0, other: 4 });
    });
  });

  describe("combineRunCounts", () => {
    it("sums counts from both inputs", () => {
      const a = { work: 3, cleanup: 1, other: 2 };
      const b = { work: 1, cleanup: 2, other: 0 };
      expect(combineRunCounts(a, b)).toEqual({ work: 4, cleanup: 3, other: 2 });
    });

    it("handles zeros", () => {
      const a = { work: 0, cleanup: 0, other: 0 };
      const b = { work: 0, cleanup: 0, other: 0 };
      expect(combineRunCounts(a, b)).toEqual({ work: 0, cleanup: 0, other: 0 });
    });
  });

  describe("formatAgentRuns", () => {
    it("returns em dash when all counts are zero", () => {
      expect(formatAgentRuns({ work: 0, cleanup: 0, other: 0 })).toBe("—");
    });

    it("formats single category", () => {
      expect(formatAgentRuns({ work: 3, cleanup: 0, other: 0 })).toBe("Work 3");
    });

    it("formats multiple categories with separator", () => {
      expect(formatAgentRuns({ work: 2, cleanup: 1, other: 3 })).toBe("Work 2 · Cleanup 1 · Other 3");
    });

    it("skips zero categories", () => {
      expect(formatAgentRuns({ work: 0, cleanup: 2, other: 0 })).toBe("Cleanup 2");
    });
  });
});
