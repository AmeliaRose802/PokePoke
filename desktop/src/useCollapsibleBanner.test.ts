import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useCollapsibleBanner } from "./useCollapsibleBanner";

describe("useCollapsibleBanner", () => {
  const storageKey = "pokepoke-banner-collapsed";

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts expanded by default", () => {
    const { result } = renderHook(() => useCollapsibleBanner());
    expect(result.current.collapsed).toBe(false);
  });

  it("reads initial collapsed state from localStorage", () => {
    localStorage.setItem(storageKey, "true");
    const { result } = renderHook(() => useCollapsibleBanner());
    expect(result.current.collapsed).toBe(true);
  });

  it("toggles collapsed state", () => {
    const { result } = renderHook(() => useCollapsibleBanner());
    expect(result.current.collapsed).toBe(false);

    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);

    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(false);
  });

  it("persists collapsed state to localStorage", () => {
    const { result } = renderHook(() => useCollapsibleBanner());

    act(() => result.current.toggle());
    expect(localStorage.getItem(storageKey)).toBe("true");

    act(() => result.current.toggle());
    expect(localStorage.getItem(storageKey)).toBe("false");
  });

  it("handles localStorage errors gracefully", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });

    const { result } = renderHook(() => useCollapsibleBanner());
    expect(result.current.collapsed).toBe(false);

    // Toggle should still work in-memory even if storage fails
    act(() => result.current.toggle());
    expect(result.current.collapsed).toBe(true);
  });
});
