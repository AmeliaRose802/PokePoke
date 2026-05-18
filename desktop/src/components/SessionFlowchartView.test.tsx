/**
 * Tests for SessionFlowchartView component rendering.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentInfo } from "../types";

const mockGetAgentDetail = vi.fn();
const mockBridge = {
  getAgentDetail: mockGetAgentDetail,
};

vi.mock("../useBridge", () => ({
  useBridge: () => mockBridge,
}));

import { SessionFlowchartView } from "./SessionFlowchartView";

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

describe("SessionFlowchartView", () => {
  beforeEach(() => {
    mockGetAgentDetail.mockReset();
  });

  it("renders the shell container", () => {
    const { container } = render(
      <SessionFlowchartView
        agents={[]}
        stats={null}
        agentName="test-agent"
        currentSessionId={null}
        activeModel={null}
      />,
    );
    expect(container.querySelector(".sf-shell")).toBeInTheDocument();
  });

  it("shows empty state when no agents", () => {
    const { container } = render(
      <SessionFlowchartView
        agents={[]}
        stats={null}
        agentName="test-agent"
        currentSessionId={null}
        activeModel={null}
      />,
    );
    const svgText = container.querySelector(".sf-svg text");
    expect(svgText).toBeTruthy();
  });

  it("renders info bar with agent name", () => {
    const { container } = render(
      <SessionFlowchartView
        agents={[]}
        stats={null}
        agentName="sea_snake"
        currentSessionId={null}
        activeModel="claude-opus-4.6"
      />,
    );
    const infoBar = container.querySelector(".sf-info-bar");
    expect(infoBar?.textContent).toContain("sea_snake");
    expect(infoBar?.textContent).toContain("claude-opus-4.6");
  });

  it("renders legend bar with all status types", () => {
    const { container } = render(
      <SessionFlowchartView
        agents={[]}
        stats={null}
        agentName="test"
        currentSessionId={null}
        activeModel={null}
      />,
    );
    const legend = container.querySelector(".sf-legend-bar");
    expect(legend?.textContent).toContain("Done");
    expect(legend?.textContent).toContain("Active");
    expect(legend?.textContent).toContain("Pending");
    expect(legend?.textContent).toContain("Failed");
    expect(legend?.textContent).toContain("Maintenance");
  });

  it("renders info bar stats", () => {
    const { container } = render(
      <SessionFlowchartView
        agents={[]}
        stats={{ elapsed_time: 3661 } as never}
        agentName="test"
        currentSessionId={null}
        activeModel="claude"
      />,
    );
    const infoBar = container.querySelector(".sf-info-bar");
    expect(infoBar?.textContent).toContain("01:01:01");
    expect(infoBar?.textContent).toContain("claude");
  });

  it("renders active slots for running agents", () => {
    const agent = mkAgent({
      agent_id: "w1",
      status: "running",
      work_item_id: "task-1",
    });
    const { container } = render(
      <SessionFlowchartView
        agents={[agent]}
        stats={null}
        agentName="test"
        currentSessionId={null}
        activeModel={null}
      />,
    );
    // Should have ACTIVE label
    const svgTexts = Array.from(container.querySelectorAll(".sf-svg text"));
    const activeLabel = svgTexts.find((t) => t.textContent === "ACTIVE");
    expect(activeLabel).toBeTruthy();
  });

  it("renders both completed and active sections", () => {
    const done = mkAgent({
      agent_id: "d1",
      status: "success",
      work_item_id: "item-1",
      session_id: "s1",
    });
    const active = mkAgent({
      agent_id: "a1",
      status: "running",
      work_item_id: "item-2",
      session_id: "s1",
    });
    const { container } = render(
      <SessionFlowchartView
        agents={[done, active]}
        stats={null}
        agentName="test"
        currentSessionId="s1"
        activeModel={null}
      />,
    );
    // Should have both the dimmed completed section and the active section
    const groups = container.querySelectorAll(".sf-svg g");
    expect(groups.length).toBeGreaterThan(0);
  });

  it("loads detailed logs for a clicked stage", async () => {
    mockGetAgentDetail.mockResolvedValue({
      agent_id: "w1",
      name: "Worker",
      iteration: 1,
      status: "running",
      recent_logs: [],
      log_lines: ["line one", "line two"],
      modified_files: [],
    });

    render(
      <SessionFlowchartView
        agents={[
          mkAgent({
            agent_id: "w1",
            status: "running",
            work_item_id: "item-1",
            recent_logs: [],
          }),
        ]}
        stats={null}
        agentName="test"
        currentSessionId={null}
        activeModel={null}
      />,
    );

    fireEvent.click(screen.getByText("Work Agent"));

    await waitFor(() => {
      expect(screen.getByText("line one")).toBeInTheDocument();
      expect(screen.getByText("line two")).toBeInTheDocument();
    });
  });
});
