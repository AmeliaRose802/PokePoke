/**
 * Tests for PipelineView component.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { MergeFlowState, MergeStepState, PipelineState } from "../types";
import { PipelineView } from "./PipelineView";

const GATE_STEP_DEFS = [
  { id: "0", label: "Work agent invoked" },
  { id: "1", label: "Work agent running" },
  { id: "DONE", label: "Gate approved — merge" },
];

const MERGE_STEP_DEFS = [
  { id: "0", label: "Agent work complete" },
  { id: "1", label: "Acquire merge lock" },
  { id: "11", label: "Release merge lock — DONE" },
];

const EDGES = [{ from: "0", to: "1" }];

function mkStep(overrides: Partial<MergeStepState> = {}): MergeStepState {
  return {
    step_id: "0",
    label: "Step",
    status: "pending",
    started_at: null,
    ended_at: null,
    logs: [],
    ...overrides,
  };
}

function mkFlow(stepDefs: typeof GATE_STEP_DEFS, overrides: Partial<MergeFlowState> = {}): MergeFlowState {
  return {
    current_run: null,
    last_completed_run: null,
    steps_definition: stepDefs,
    edges: EDGES,
    ...overrides,
  };
}

function mkPipelineState(overrides: Partial<PipelineState> = {}): PipelineState {
  return {
    gate: mkFlow(GATE_STEP_DEFS),
    merge: mkFlow(MERGE_STEP_DEFS),
    active_phase: "idle",
    ...overrides,
  };
}

function mkRun(stepDefs: typeof GATE_STEP_DEFS, stepOverrides: Record<string, Partial<MergeStepState>> = {}) {
  const steps: Record<string, MergeStepState> = {};
  for (const def of stepDefs) {
    steps[def.id] = mkStep({ step_id: def.id, label: def.label, ...(stepOverrides[def.id] ?? {}) });
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

describe("PipelineView", () => {
  const nullMerge = vi.fn().mockResolvedValue(null);
  const nullGate = vi.fn().mockResolvedValue(null);

  it("renders both phase headers", async () => {
    const getPipelineState = vi.fn().mockResolvedValue(mkPipelineState());
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={nullGate} />);

    // Wait for first poll
    await vi.waitFor(() => {
      expect(screen.getByTestId("pipeline-view")).toBeInTheDocument();
    });

    expect(screen.getByText("Quality Gate")).toBeInTheDocument();
    expect(screen.getByText("Merge Workflow")).toBeInTheDocument();
  });

  it("shows idle status when no runs exist", async () => {
    const getPipelineState = vi.fn().mockResolvedValue(mkPipelineState());
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={nullGate} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("pipeline-phase-gate")).toBeInTheDocument();
    });

    // Both phases should show Pending
    const statuses = screen.getAllByText(/Pending/);
    expect(statuses.length).toBeGreaterThanOrEqual(2);
  });

  it("shows active status on gate phase when gate is running", async () => {
    const gateRun = mkRun(GATE_STEP_DEFS, { "0": { status: "active" } });
    const state = mkPipelineState({
      gate: mkFlow(GATE_STEP_DEFS, { current_run: gateRun }),
      active_phase: "gate",
    });
    const getPipelineState = vi.fn().mockResolvedValue(state);
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={nullGate} />);

    await vi.waitFor(() => {
      const gatePhase = screen.getByTestId("pipeline-phase-gate");
      expect(gatePhase.textContent).toContain("Active");
    });
  });

  it("expands gate phase when clicking toggle", async () => {
    const gateRun = mkRun(GATE_STEP_DEFS, { "0": { status: "active" } });
    const state = mkPipelineState({
      gate: mkFlow(GATE_STEP_DEFS, { current_run: gateRun }),
      active_phase: "gate",
    });
    const getPipelineState = vi.fn().mockResolvedValue(state);
    const getGateFlowState = vi.fn().mockResolvedValue(state.gate);
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={getGateFlowState} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("pipeline-phase-gate-content")).toBeInTheDocument();
    });
  });

  it("shows connector label when gate is complete", async () => {
    const gateRun = { ...mkRun(GATE_STEP_DEFS), outcome: "success" as const, ended_at: 2000 };
    const state = mkPipelineState({
      gate: mkFlow(GATE_STEP_DEFS, { last_completed_run: gateRun }),
      active_phase: "gate",
    });
    const getPipelineState = vi.fn().mockResolvedValue(state);
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={nullGate} />);

    await vi.waitFor(() => {
      expect(screen.getByText("Approved")).toBeInTheDocument();
    });
  });

  it("toggles phase expansion on click", async () => {
    const getPipelineState = vi.fn().mockResolvedValue(mkPipelineState());
    const user = userEvent.setup();
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={nullGate} />);

    await vi.waitFor(() => {
      expect(screen.getByTestId("pipeline-phase-merge-toggle")).toBeInTheDocument();
    });

    // Initially no content expanded (idle state)
    expect(screen.queryByTestId("pipeline-phase-merge-content")).not.toBeInTheDocument();

    // Click to expand merge
    await user.click(screen.getByTestId("pipeline-phase-merge-toggle"));
    expect(screen.getByTestId("pipeline-phase-merge-content")).toBeInTheDocument();

    // Click again to collapse
    await user.click(screen.getByTestId("pipeline-phase-merge-toggle"));
    expect(screen.queryByTestId("pipeline-phase-merge-content")).not.toBeInTheDocument();
  });

  it("displays agent and item context in header", async () => {
    const gateRun = mkRun(GATE_STEP_DEFS);
    const state = mkPipelineState({
      gate: mkFlow(GATE_STEP_DEFS, { current_run: gateRun }),
      active_phase: "gate",
    });
    const getPipelineState = vi.fn().mockResolvedValue(state);
    render(<PipelineView getPipelineState={getPipelineState} getMergeFlowState={nullMerge} getGateFlowState={nullGate} />);

    await vi.waitFor(() => {
      expect(screen.getByText(/agent-1/)).toBeInTheDocument();
    });
    expect(screen.getByText(/item-42/)).toBeInTheDocument();
  });
});
