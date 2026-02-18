import { describe, it, expect } from 'vitest';
import type { SessionStats } from '../types';
import { getCompletedItems, getDoneCount } from './stats';

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
});
