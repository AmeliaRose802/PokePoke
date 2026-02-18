import { describe, it, expect } from 'vitest';
import type { ModelPerformanceSummary, SessionStats } from '../types';
import { getCompletedItems, getDoneCount, inferCurrentModel } from './stats';

describe('stats helpers', () => {
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
});
