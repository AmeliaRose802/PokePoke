import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

/** A component that always throws. */
function AlwaysThrow(): never {
  throw new Error("insertBefore: not a child of this node");
}

/** A simple child component */
function GoodChild() {
  return <div data-testid="child">OK</div>;
}

describe("ErrorBoundary", () => {
  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <GoodChild />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("catches render errors and unmounts the subtree", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <AlwaysThrow />
      </ErrorBoundary>,
    );

    // Child should be gone (boundary caught the error)
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();

    spy.mockRestore();
    warnSpy.mockRestore();
  });

  it("renders fallback when provided", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <ErrorBoundary fallback={<div data-testid="fallback">Recovering...</div>}>
        <AlwaysThrow />
      </ErrorBoundary>,
    );

    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();

    spy.mockRestore();
    warnSpy.mockRestore();
  });

  it("logs a warning via componentDidCatch", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <AlwaysThrow />
      </ErrorBoundary>,
    );

    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("[ErrorBoundary]"),
      expect.any(String),
      expect.anything(),
    );

    spy.mockRestore();
    warnSpy.mockRestore();
  });
});
