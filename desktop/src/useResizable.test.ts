import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useResizable } from "./useResizable";

describe("useResizable", () => {
  it("returns the default initial fraction", () => {
    const { result } = renderHook(() => useResizable());
    expect(result.current.fraction).toBeCloseTo(0.667, 2);
    expect(result.current.isDragging).toBe(false);
  });

  it("accepts a custom initial fraction", () => {
    const { result } = renderHook(() =>
      useResizable({ initialFraction: 0.5 })
    );
    expect(result.current.fraction).toBeCloseTo(0.5);
  });

  it("starts dragging on mousedown", () => {
    const { result } = renderHook(() => useResizable());
    const fakeEvent = {
      preventDefault: () => {},
    } as React.MouseEvent;

    act(() => {
      result.current.handleProps.onMouseDown(fakeEvent);
    });

    expect(result.current.isDragging).toBe(true);
  });

  it("stops dragging on mouseup", () => {
    const { result } = renderHook(() => useResizable());
    const fakeEvent = {
      preventDefault: () => {},
    } as React.MouseEvent;

    act(() => {
      result.current.handleProps.onMouseDown(fakeEvent);
    });
    expect(result.current.isDragging).toBe(true);

    act(() => {
      document.dispatchEvent(new MouseEvent("mouseup"));
    });
    expect(result.current.isDragging).toBe(false);
  });

  it("exposes data-dragging attribute in handleProps", () => {
    const { result } = renderHook(() => useResizable());
    expect(result.current.handleProps["data-dragging"]).toBe(false);

    const fakeEvent = {
      preventDefault: () => {},
    } as React.MouseEvent;

    act(() => {
      result.current.handleProps.onMouseDown(fakeEvent);
    });
    expect(result.current.handleProps["data-dragging"]).toBe(true);
  });

  it("provides a containerRef", () => {
    const { result } = renderHook(() => useResizable());
    expect(result.current.containerRef).toBeDefined();
    expect(result.current.containerRef.current).toBeNull();
  });
});
