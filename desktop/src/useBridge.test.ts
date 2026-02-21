/**
 * Tests for useBridge utilities (shallowEqual).
 */

import { describe, it, expect } from 'vitest';
import { shallowEqual } from './useBridge';

describe('shallowEqual', () => {
  it('returns true for identical primitives', () => {
    expect(shallowEqual(1, 1)).toBe(true);
    expect(shallowEqual('hello', 'hello')).toBe(true);
    expect(shallowEqual(true, true)).toBe(true);
    expect(shallowEqual(null, null)).toBe(true);
    expect(shallowEqual(undefined, undefined)).toBe(true);
  });

  it('returns false for different primitives', () => {
    expect(shallowEqual(1, 2)).toBe(false);
    expect(shallowEqual('a', 'b')).toBe(false);
    expect(shallowEqual(true, false)).toBe(false);
    expect(shallowEqual(null, undefined)).toBe(false);
  });

  it('returns true for objects with same keys and values', () => {
    expect(shallowEqual({ a: 1, b: 'x' }, { a: 1, b: 'x' })).toBe(true);
  });

  it('returns false when a key value differs', () => {
    expect(shallowEqual({ a: 1 }, { a: 2 })).toBe(false);
  });

  it('returns false when key count differs', () => {
    expect(shallowEqual({ a: 1 }, { a: 1, b: 2 })).toBe(false);
    expect(shallowEqual({ a: 1, b: 2 }, { a: 1 })).toBe(false);
  });

  it('returns false when comparing object to null', () => {
    expect(shallowEqual({ a: 1 }, null)).toBe(false);
    expect(shallowEqual(null, { a: 1 })).toBe(false);
  });

  it('does NOT deep-compare nested objects (returns false for new refs)', () => {
    expect(shallowEqual({ a: { b: 1 } }, { a: { b: 1 } })).toBe(false);
  });

  it('returns true for same nested reference', () => {
    const inner = { b: 1 };
    expect(shallowEqual({ a: inner }, { a: inner })).toBe(true);
  });

  it('handles empty objects', () => {
    expect(shallowEqual({}, {})).toBe(true);
  });

  it('handles NaN via Object.is', () => {
    expect(shallowEqual(NaN, NaN)).toBe(true);
  });
});
