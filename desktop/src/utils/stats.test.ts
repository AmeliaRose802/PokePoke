import { describe, expect,it } from 'vitest';

import type { ModelHistoryEntry, ModelPerformanceSummary, SessionStats } from '../types';
import { aggregateHistory, buildCompletionSeries, buildSuccessRateSeries, formatDurationWithSpread, getCompletedItems, getDoneCount, inferCurrentModel } from './stats';

describe('stats helpers', () => {
  describe('formatDurationWithSpread', () => {
    it('shows median ±stddev when stddev is non-zero', () => {
      // 2610s = 43.5m, 720s = 12.0m
      expect(formatDurationWithSpread(2610, 720)).toBe('43.5m ±12.0m');
    });

    it('shows only median when stddev is zero', () => {
      expect(formatDurationWithSpread(59, 0)).toBe('59s');
    });

    it('shows only median when stddev is undefined', () => {
      expect(formatDurationWithSpread(120, undefined)).toBe('2.0m');
    });

    it('handles seconds-range values', () => {
      expect(formatDurationWithSpread(30, 5)).toBe('30s ±5s');
    });

    it('handles hours-range values', () => {
      expect(formatDurationWithSpread(7200, 3600)).toBe('2.0h ±1.0h');
    });

    it('handles undefined median', () => {
      expect(formatDurationWithSpread(undefined, 10)).toBe('0s ±10s');
    });
  });

  describe('getCompletedItems', () => {
    it('dedupes by id and ignores missing ids', () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        completed_items: [
          { id: 'A', title: 'First' },
          { id: 'A', title: 'Duplicate' },
          { id: '  B  ', status: 'done' },
          { id: '   ' },
        ],
      };

      const result = getCompletedItems(stats);

      expect(result).toHaveLength(2);
      expect(result.map((item) => item.id)).toEqual(['A', 'B']);
    });
  });

  describe('getDoneCount', () => {
    it('prioritizes items_completed counter over array length', () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        completed_items: [
          { id: 'X' },
          { id: 'Y' },
          { id: 'Y' },
        ],
        items_completed: 10,
      };

      // Should return 10 (counter), not 2 (deduplicated array length)
      expect(getDoneCount(stats)).toBe(10);
    });

    it('falls back to array length when counter is missing or zero', () => {
      const withEmptyCounter: SessionStats = {
        elapsed_time: 0,
        completed_items: [{ id: 'A' }, { id: 'B' }],
        items_completed: 0,
      };

      const withoutCounter: SessionStats = {
        elapsed_time: 0,
        completed_items: [{ id: 'X' }, { id: 'Y' }, { id: 'Y' }],
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

    it('returns zero when both counter and array are missing', () => {
      const stats: SessionStats = {
        elapsed_time: 0,
      };

      expect(getDoneCount(stats)).toBe(0);
    });
  });

  describe('inferCurrentModel', () => {
    const leaderboard: Record<string, ModelPerformanceSummary> = {
      'gemini-3-pro': { success_rate: 0.9 } as ModelPerformanceSummary,
      'gpt-5.1': { success_rate: 0.75 } as ModelPerformanceSummary,
    };

    it('prefers the live active agent model when provided', () => {
      const stats: SessionStats = { elapsed_time: 0 };

      const result = inferCurrentModel(stats, leaderboard, 'gpt-5.1');

      expect(result).toEqual({
        model: 'gpt-5.1',
        gatePassed: null,
        successRate: 0.75,
      });
    });

    it('falls back to latest completion when no active agent model is provided', () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        model_completions: [
          {
            item_id: 'AA7Y',
            model: 'gemini-3-pro',
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
        model: 'gemini-3-pro',
        gatePassed: true,
        successRate: 0.9,
      });
    });
  });

  function makeEntry(overrides: Partial<ModelHistoryEntry> = {}): ModelHistoryEntry {
    return {
      item_id: 'test-1',
      model: 'test-model',
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
      timestamp: '2026-02-20T10:00:00+00:00',
      ...overrides,
    };
  }

  describe('aggregateHistory', () => {
    it('counts entries with success=true as completed', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', success: true, gate_passed: true }),
        makeEntry({ timestamp: '2026-02-20T11:00:00+00:00', success: true, gate_passed: true }),
        makeEntry({ timestamp: '2026-02-20T12:00:00+00:00', success: false, gate_passed: false }),
      ];
      const result = aggregateHistory(history);
      expect(result).toHaveLength(1);
      expect(result[0].successCount).toBe(2);
      expect(result[0].decidedCount).toBe(3);
    });

    it('uses success field even when gate_passed is null', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', success: true, gate_passed: null }),
        makeEntry({ timestamp: '2026-02-20T11:00:00+00:00', success: true, gate_passed: null }),
      ];
      const result = aggregateHistory(history);
      expect(result[0].successCount).toBe(2);
      expect(result[0].decidedCount).toBe(2);
    });

    it('falls back to gate_passed when success is undefined', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', gate_passed: true }),
        makeEntry({ timestamp: '2026-02-20T11:00:00+00:00', gate_passed: false }),
      ];
      const result = aggregateHistory(history);
      expect(result[0].successCount).toBe(1);
      expect(result[0].decidedCount).toBe(2);
    });

    it('groups by date across multiple days', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-19T10:00:00+00:00', success: true }),
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', success: true }),
        makeEntry({ timestamp: '2026-02-20T11:00:00+00:00', success: false }),
      ];
      const result = aggregateHistory(history);
      expect(result).toHaveLength(2);
      expect(result[0].dateLabel).toBe('2026-02-19');
      expect(result[0].successCount).toBe(1);
      expect(result[1].dateLabel).toBe('2026-02-20');
      expect(result[1].successCount).toBe(1);
      expect(result[1].decidedCount).toBe(2);
    });

    it('returns empty array for empty history', () => {
      expect(aggregateHistory([])).toHaveLength(0);
    });
  });

  describe('buildCompletionSeries', () => {
    it('returns success counts per day', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', success: true }),
        makeEntry({ timestamp: '2026-02-20T11:00:00+00:00', success: true }),
        makeEntry({ timestamp: '2026-02-21T10:00:00+00:00', success: false }),
      ];
      const series = buildCompletionSeries(history);
      expect(series).toHaveLength(2);
      expect(series[0]).toEqual({ label: '2026-02-20', value: 2 });
      expect(series[1]).toEqual({ label: '2026-02-21', value: 0 });
    });

    it('returns empty array for empty history', () => {
      expect(buildCompletionSeries([])).toHaveLength(0);
    });
  });

  describe('buildSuccessRateSeries', () => {
    it('calculates success percentage per day', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', success: true }),
        makeEntry({ timestamp: '2026-02-20T11:00:00+00:00', success: false }),
      ];
      const series = buildSuccessRateSeries(history);
      expect(series).toHaveLength(1);
      expect(series[0].value).toBe(50);
    });

    it('returns 0% when no decided items exist', () => {
      const history = [
        makeEntry({ timestamp: '2026-02-20T10:00:00+00:00', gate_passed: null }),
      ];
      const series = buildSuccessRateSeries(history);
      expect(series).toHaveLength(1);
      expect(series[0].value).toBe(0);
    });

    it('returns empty array for empty history', () => {
      expect(buildSuccessRateSeries([])).toHaveLength(0);
    });
  });
});
