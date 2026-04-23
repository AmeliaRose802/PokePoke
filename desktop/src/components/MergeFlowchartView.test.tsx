/**
 * Tests for MergeFlowchartView component.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MergeFlowState, MergeStepState } from "../types";
import { MergeFlowchartView } from "./MergeFlowchartView";

const STEP_DEFS = [
  { id: "0", label: "Agent work complete" },
  { id: "1", label: "Acquire merge lock" },
  { id: "2", label: "Main repo clean?" },
  { id: "11", label: "Merge --no-ff branch" },
  { id: "16", label: "Release merge lock — DONE" },
];

const EDGES = [
  { from: "0", to: "1" },
  { from: "1", to: "2" },
];

function mkStep(overrides: Partial<MergeStepState> = {}): MergeStepState {
  return {
    step_id: "0",
    label: "Agent work complete",
    status: "pending",
    started_at: null,
    ended_at: null,
    logs: [],
    ...overrides,
  };
}

function mkFlowState(overrides: Partial<MergeFlowState> = {}): MergeFlowState {
  return {
    current_run: null,
    last_completed_run: null,
    steps_definition: STEP_DEFS,
    edges: EDGES,
    ...overrides,
  };
}

function mkRun(stepOverrides: Record<string, Partial<MergeStepState>> = {}) {
  const steps: Record<string, MergeStepState> = {};
  for (const def of STEP_DEFS) {
    steps[def.id] = mkStep({
      step_id: def.id,
      label: def.label,
      ...(stepOverrides[def.id] ?? {}),
    });
  }
  return {
    agent_id: "agent-1",
    item_id: "item-42",
    started_at: 1000,
    ended_at: null as number | null,
    outcome: "in_progress" as const,
    steps,
  };
}

describe("MergeFlowchartView", () => {
  it("renders empty state when no merge data", async () => {
    const getMergeFlowState = vi.fn().mockResolvedValue(null);
    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);
    expect(screen.getByTestId("merge-flowchart-view")).toBeInTheDocument();
    expect(screen.getByText("No merge activity yet.")).toBeInTheDocument();
  });

  it("renders only non-pending step nodes from a current run", async () => {
    const run = mkRun({ "0": { status: "done" }, "1": { status: "active" } });
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    // Wait for the first poll to populate state
    await vi.waitFor(() => {
      expect(screen.getByTestId("merge-step-0")).toBeInTheDocument();
    });

    expect(screen.getByTestId("merge-step-1")).toBeInTheDocument();
    // Steps still pending should NOT be rendered
    expect(screen.queryByTestId("merge-step-2")).not.toBeInTheDocument();
    expect(screen.queryByTestId("merge-step-11")).not.toBeInTheDocument();
    expect(screen.queryByTestId("merge-step-16")).not.toBeInTheDocument();
  });

  it("renders pending steps when no step has started yet", async () => {
    const run = mkRun();
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("merge-step-0")).toBeInTheDocument();
    });

    expect(screen.getByTestId("merge-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("merge-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("merge-step-11")).toBeInTheDocument();
    expect(screen.getByTestId("merge-step-16")).toBeInTheDocument();
  });

  it("shows Live indicator for current run", async () => {
    const run = mkRun({ "0": { status: "active" } });
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByText("● Live")).toBeInTheDocument();
    });
  });

  it("shows Completed indicator for last completed run", async () => {
    const run = { ...mkRun({ "0": { status: "done" } }), outcome: "success" as const, ended_at: 2000 };
    const state = mkFlowState({ last_completed_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByText("✓ Completed")).toBeInTheDocument();
    });
  });

  it("shows Failed indicator for failed run", async () => {
    const run = { ...mkRun({ "0": { status: "failed" } }), outcome: "failed" as const, ended_at: 2000 };
    const state = mkFlowState({ last_completed_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByText("✗ Failed")).toBeInTheDocument();
    });
  });

  it("opens log panel when clicking a step with logs", async () => {
    const run = mkRun({
      "1": { status: "done", logs: ["Acquired lock", "Lock timeout: 5s"] },
    });
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);
    const user = userEvent.setup();

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("merge-step-1")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("merge-step-1"));

    expect(screen.getByTestId("merge-step-log-panel")).toBeInTheDocument();
    expect(screen.getByText("Acquired lock")).toBeInTheDocument();
    expect(screen.getByText("Lock timeout: 5s")).toBeInTheDocument();
  });

  it("closes log panel when clicking the same step again", async () => {
    const run = mkRun({
      "1": { status: "done", logs: ["Log line"] },
    });
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);
    const user = userEvent.setup();

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("merge-step-1")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("merge-step-1"));
    expect(screen.getByTestId("merge-step-log-panel")).toBeInTheDocument();

    await user.click(screen.getByTestId("merge-step-1"));
    expect(screen.queryByTestId("merge-step-log-panel")).not.toBeInTheDocument();
  });

  it("closes log panel via close button", async () => {
    const run = mkRun({
      "2": { status: "failed", logs: ["Dirty files"] },
    });
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);
    const user = userEvent.setup();

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("merge-step-2")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("merge-step-2"));
    expect(screen.getByTestId("merge-step-log-panel")).toBeInTheDocument();

    await user.click(screen.getByTitle("Close log panel"));
    expect(screen.queryByTestId("merge-step-log-panel")).not.toBeInTheDocument();
  });

  it("shows 'No logs' message for step without logs", async () => {
    const run = mkRun({ "2": { status: "done", logs: [] } });
    const state = mkFlowState({ current_run: run });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);
    const user = userEvent.setup();

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("merge-step-2")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("merge-step-2"));
    expect(screen.getByText("No logs for this step yet.")).toBeInTheDocument();
  });

  it("prefers current_run over last_completed_run", async () => {
    const currentRun = mkRun({ "0": { status: "active" } });
    currentRun.agent_id = "current-agent";
    const lastRun = { ...mkRun({ "0": { status: "done" } }), agent_id: "old-agent", outcome: "success" as const, ended_at: 2000 };
    const state = mkFlowState({ current_run: currentRun, last_completed_run: lastRun });
    const getMergeFlowState = vi.fn().mockResolvedValue(state);

    render(<MergeFlowchartView getMergeFlowState={getMergeFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByText(/current-agent/)).toBeInTheDocument();
    });
  });
});
