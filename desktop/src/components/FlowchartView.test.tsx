/**
 * Tests for FlowchartView component rendering.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AgentInfo } from "../types";
import { FlowchartView } from "./FlowchartView";

// Mock useBridge since FlowchartView doesn't use it directly,
// but its parent (AgentLogPanel) does. FlowchartView is pure.

function mkAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    agent_id: "agent-1",
    name: "Worker",
    iteration: 1,
    status: "running",
    recent_logs: [],
    modified_files: [],
    ...overrides,
  };
}

describe("FlowchartView", () => {
  it("renders the flowchart container", () => {
    const agent = mkAgent({ recent_logs: ["Working..."] });
    render(<FlowchartView agent={agent} allAgents={[agent]} />);
    expect(screen.getByTestId("flowchart-view")).toBeInTheDocument();
  });

  it("renders pipeline nodes for a running agent", () => {
    const agent = mkAgent({
      agent_id: "a1",
      status: "running",
      recent_logs: ["Hello"],
      work_item_id: "task-1",
    });
    render(<FlowchartView agent={agent} allAgents={[agent]} />);

    expect(screen.getByTestId("flowchart-node-a1-claim")).toBeInTheDocument();
    expect(screen.getByTestId("flowchart-node-a1-worktree")).toBeInTheDocument();
    expect(screen.getByTestId("flowchart-node-a1-ai")).toBeInTheDocument();
    expect(screen.getByTestId("flowchart-node-a1-validation")).toBeInTheDocument();
  });

  it("renders completed node for success agent", () => {
    const agent = mkAgent({
      agent_id: "a1",
      status: "success",
      recent_logs: ["Done"],
      work_item_id: "task-1",
      modified_files: ["f.ts"],
    });
    render(<FlowchartView agent={agent} allAgents={[agent]} />);

    expect(screen.getByTestId("flowchart-node-a1-complete")).toBeInTheDocument();
  });

  it("renders failed node for failed agent", () => {
    const agent = mkAgent({
      agent_id: "a1",
      status: "failed",
      work_item_id: "task-1",
    });
    render(<FlowchartView agent={agent} allAgents={[agent]} />);

    expect(screen.getByTestId("flowchart-node-a1-failed")).toBeInTheDocument();
  });

  it("shows attempts badge for multi-retry agents", () => {
    const root = mkAgent({
      agent_id: "a1",
      card_id: "card-1",
      status: "failed",
      work_item_id: "task-1",
    });
    const retry = mkAgent({
      agent_id: "a2",
      card_id: "card-2",
      parent_card_id: "card-1",
      status: "success",
      iteration: 2,
      work_item_id: "task-1",
      recent_logs: ["Retry"],
      modified_files: ["f.ts"],
    });

    render(<FlowchartView agent={root} allAgents={[root, retry]} />);

    expect(screen.getByText("2 attempts")).toBeInTheDocument();
    // Should have two attempt columns
    expect(screen.getByTestId("flowchart-attempt-1")).toBeInTheDocument();
    expect(screen.getByTestId("flowchart-attempt-2")).toBeInTheDocument();
  });

  it("does not show attempts badge for single attempt", () => {
    const agent = mkAgent({ status: "running", recent_logs: ["hi"] });
    render(<FlowchartView agent={agent} allAgents={[agent]} />);

    expect(screen.queryByText(/attempts/i)).not.toBeInTheDocument();
  });

  it("renders Pipeline Progress title", () => {
    const agent = mkAgent({ recent_logs: ["hi"] });
    render(<FlowchartView agent={agent} allAgents={[agent]} />);

    expect(screen.getByText("Pipeline Progress")).toBeInTheDocument();
  });
});
