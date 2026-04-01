import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConcurrencyTimeline } from "../types";
import { ConcurrencyChart } from "./ConcurrencyChart";

const emptyData: ConcurrencyTimeline = {
  lifecycle: [],
  completions: [],
  failures: [],
};

const sampleData: ConcurrencyTimeline = {
  lifecycle: [
    { ts: "2024-01-15 09:30:00", active: 1, max: 4, slots: 3, mem: 8192 },
    { ts: "2024-01-15 09:31:00", active: 3, max: 4, slots: 1, mem: 6144 },
    { ts: "2024-01-15 09:32:00", active: 4, max: 4, slots: 0, mem: 4096 },
    { ts: "2024-01-15 09:33:00", active: 2, max: 4, slots: 2, mem: 5120 },
  ],
  completions: [{ ts: "2024-01-15 09:32:30", item_id: "ITEM-1" }],
  failures: [{ ts: "2024-01-15 09:33:00", item_id: "ITEM-2" }],
};

describe("ConcurrencyChart", () => {
  it("shows empty state when no lifecycle data", () => {
    render(<ConcurrencyChart data={emptyData} />);
    expect(screen.getByText("No lifecycle data yet")).toBeTruthy();
  });

  it("renders chart with lifecycle data", () => {
    render(<ConcurrencyChart data={sampleData} />);
    expect(screen.getByText("Concurrent agents over time")).toBeTruthy();
    // Should not show empty message
    expect(screen.queryByText("No lifecycle data yet")).toBeNull();
  });

  it("renders SVG elements", () => {
    const { container } = render(<ConcurrencyChart data={sampleData} />);
    const svg = container.querySelector(".concurrency-chart-svg");
    expect(svg).toBeTruthy();

    // Should have polylines for active and max lines
    const polylines = svg?.querySelectorAll("polyline");
    expect(polylines?.length).toBeGreaterThanOrEqual(2);
  });

  it("renders completion dots (green)", () => {
    const { container } = render(<ConcurrencyChart data={sampleData} />);
    const circles = container.querySelectorAll("circle");
    // At least 1 for completion and 1 for failure
    expect(circles.length).toBeGreaterThanOrEqual(2);
  });

  it("renders legend items", () => {
    render(<ConcurrencyChart data={sampleData} />);
    expect(screen.getByText("Active")).toBeTruthy();
    expect(screen.getByText("Max")).toBeTruthy();
    expect(screen.getByText("Completed")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
  });

  it("renders x-axis time labels", () => {
    const { container } = render(<ConcurrencyChart data={sampleData} />);
    const xLabels = container.querySelectorAll(".concurrency-chart-x-label");
    expect(xLabels.length).toBeGreaterThan(0);
  });

  it("handles single lifecycle entry", () => {
    const singleEntry: ConcurrencyTimeline = {
      lifecycle: [{ ts: "2024-01-15 09:30:00", active: 2, max: 4, slots: 2, mem: 8192 }],
      completions: [],
      failures: [],
    };
    const { container } = render(<ConcurrencyChart data={singleEntry} />);
    expect(container.querySelector(".concurrency-chart-svg")).toBeTruthy();
  });
});
