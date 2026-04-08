import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ProcessSnapshot } from "../types";
import { ProcessUsageChart } from "./ProcessUsageChart";

const sampleData: ProcessSnapshot[] = [
  { timestamp: "2024-01-15T09:30:00", copilot_count: 2, child_count: 6, total_memory_mb: 512, cpu_percent: 15.2 },
  { timestamp: "2024-01-15T09:31:00", copilot_count: 5, child_count: 15, total_memory_mb: 1280, cpu_percent: 42.7 },
  { timestamp: "2024-01-15T09:32:00", copilot_count: 8, child_count: 24, total_memory_mb: 2048, cpu_percent: 78.3 },
  { timestamp: "2024-01-15T09:33:00", copilot_count: 4, child_count: 12, total_memory_mb: 1024, cpu_percent: 35.1 },
];

describe("ProcessUsageChart", () => {
  it("shows empty state when no data", () => {
    render(<ProcessUsageChart data={[]} />);
    expect(screen.getByText(/No process snapshots captured yet/)).toBeTruthy();
  });

  it("renders chart with data", () => {
    const { container } = render(<ProcessUsageChart data={sampleData} />);
    const svg = container.querySelector(".process-chart-svg");
    expect(svg).toBeTruthy();
  });

  it("renders all four polylines (CPU, memory, copilot, child)", () => {
    const { container } = render(<ProcessUsageChart data={sampleData} />);
    const polylines = container.querySelectorAll(".process-chart-line");
    expect(polylines.length).toBe(4);
  });

  it("renders data point markers", () => {
    const { container } = render(<ProcessUsageChart data={sampleData} />);
    const points = container.querySelectorAll(".process-chart-point");
    // 4 metrics × 4 data points = 16 markers
    expect(points.length).toBe(sampleData.length * 4);
  });

  it("renders legend items", () => {
    render(<ProcessUsageChart data={sampleData} />);
    expect(screen.getByText("CPU %")).toBeTruthy();
    expect(screen.getByText("Memory (MB)")).toBeTruthy();
    expect(screen.getByText("Copilot Processes")).toBeTruthy();
    expect(screen.getByText("Child Processes")).toBeTruthy();
  });

  it("renders x-axis time labels", () => {
    const { container } = render(<ProcessUsageChart data={sampleData} />);
    const xLabels = container.querySelectorAll(".process-chart-x-label");
    expect(xLabels.length).toBeGreaterThan(0);
  });

  it("renders left and right y-axis labels", () => {
    const { container } = render(<ProcessUsageChart data={sampleData} />);
    const leftLabels = container.querySelectorAll(".process-chart-y-label-left");
    const rightLabels = container.querySelectorAll(".process-chart-y-label-right");
    expect(leftLabels.length).toBeGreaterThan(0);
    expect(rightLabels.length).toBeGreaterThan(0);
  });

  it("handles single data point", () => {
    const single: ProcessSnapshot[] = [
      { timestamp: "2024-01-15T09:30:00", copilot_count: 3, child_count: 9, total_memory_mb: 600, cpu_percent: 25 },
    ];
    const { container } = render(<ProcessUsageChart data={single} />);
    expect(container.querySelector(".process-chart-svg")).toBeTruthy();
  });

  it("handles zero cpu_percent gracefully", () => {
    const zeroCpu: ProcessSnapshot[] = [
      { timestamp: "2024-01-15T09:30:00", copilot_count: 1, child_count: 2, total_memory_mb: 100, cpu_percent: 0 },
      { timestamp: "2024-01-15T09:31:00", copilot_count: 2, child_count: 4, total_memory_mb: 200, cpu_percent: 0 },
    ];
    const { container } = render(<ProcessUsageChart data={zeroCpu} />);
    expect(container.querySelector(".process-chart-svg")).toBeTruthy();
  });
});
