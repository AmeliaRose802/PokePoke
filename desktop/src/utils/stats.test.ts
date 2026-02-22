import { describe, expect,it } from 'vitest';

import type { ModelHistoryEntry, ModelPerformanceSummary, SessionStats } from '../types';
import { buildItemTypeBreakdown, formatDurationWithSpread, getCompletedItems, getDoneCount, inferCurrentModel } from './stats';

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
    it('returns completed_items length when available', () => {
      const stats: SessionStats = {
        elapsed_time: 0,
        completed_items: [
          { id: 'X' },
          { id: 'Y' },
          { id: 'Y' },
        ],
        items_completed: 10,
      };

      expect(getDoneCount(stats)).toBe(2);
    });

    it('falls back to items_completed when completed_items is empty or missing', () => {
      const withEmptyItems: SessionStats = {
        elapsed_time: 0,
        completed_items: [],
        items_completed: 3,
      };

      const withoutItems: SessionStats = {
        elapsed_time: 0,
        items_completed: 5,
      };

      expect(getDoneCount(withEmptyItems)).toBe(3);
      expect(getDoneCount(withoutItems)).toBe(5);
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

  describe('buildItemTypeBreakdown', () => {
    it('counts items from completed items by issue_type', () => {
      const completed = [
        { id: '1', issue_type: 'bug' },
        { id: '2', issue_type: 'bug' },
        { id: '3', issue_type: 'task' },
      ];

      const result = buildItemTypeBreakdown(completed, []);

      expect(result).toHaveLength(2);
      expect(result[0]).toMatchObject({ type: 'bug', count: 2 });
      expect(result[1]).toMatchObject({ type: 'task', count: 1 });
    });

    it('counts items from model history by item_type', () => {
      const history: ModelHistoryEntry[] = [
        { item_id: 'A', model: 'm', duration_seconds: 10, gate_passed: true, timestamp: '2026-01-01', item_type: 'feature' },
        { item_id: 'B', model: 'm', duration_seconds: 20, gate_passed: true, timestamp: '2026-01-02', item_type: 'feature' },
        { item_id: 'C', model: 'm', duration_seconds: 15, gate_passed: false, timestamp: '2026-01-03', item_type: 'bug' },
      ];

      const result = buildItemTypeBreakdown([], history);

      expect(result).toHaveLength(2);
      expect(result[0]).toMatchObject({ type: 'feature', count: 2 });
      expect(result[1]).toMatchObject({ type: 'bug', count: 1 });
    });

    it('combines both sources and defaults missing types to unknown', () => {
      const completed = [{ id: '1' }]; // no issue_type
      const history: ModelHistoryEntry[] = [
        { item_id: 'A', model: 'm', duration_seconds: 10, gate_passed: true, timestamp: '2026-01-01' }, // no item_type
      ];

      const result = buildItemTypeBreakdown(completed, history);

      expect(result).toHaveLength(1);
      expect(result[0]).toMatchObject({ type: 'unknown', count: 2 });
    });

    it('returns empty array when no items', () => {
      expect(buildItemTypeBreakdown([], [])).toEqual([]);
    });

    it('assigns distinct colors per type', () => {
      const completed = [
        { id: '1', issue_type: 'bug' },
        { id: '2', issue_type: 'task' },
        { id: '3', issue_type: 'feature' },
      ];

      const result = buildItemTypeBreakdown(completed, []);
      const colors = result.map((r) => r.color);

      expect(new Set(colors).size).toBe(3);
    });
  });
});
