/**
 * Tests for AgentLogPanel prompt section: close button and scrollability.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentInfo } from "../types";

// Mock useBridge to avoid pywebview dependency
vi.mock("../useBridge", () => ({
  useBridge: () => ({
    getAgentDetail: vi.fn().mockResolvedValue(null),
    agents: [],
  }),
}));

import { AgentLogPanel } from "./AgentLogPanel";

function mkAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    agent_id: "agent-1",
    base_agent_id: "agent-1",
    card_id: "agent-1::v1",
    name: "Worker",
    iteration: 1,
    status: "running",
    recent_logs: [],
    paused: false,
    is_history_entry: false,
    ...overrides,
  };
}

describe("AgentLogPanel prompt section", () => {
  it("renders prompt accordion with close button when agent has a prompt", () => {
    const agent = mkAgent({ agent_prompt: "Test prompt content\nLine 2" });
    render(<AgentLogPanel agent={agent} onClose={vi.fn()} />);

    const summary = screen.getByText(/Agent Prompt/);
    expect(summary).toBeInTheDocument();

    // Open the details accordion
    fireEvent.click(summary);

    // Close button should be visible inside the expanded prompt
    const closeBtn = screen.getByTitle("Collapse prompt");
    expect(closeBtn).toBeInTheDocument();
    expect(closeBtn.textContent).toContain("Close");
  });

  it("collapses the prompt section when close button is clicked", () => {
    const agent = mkAgent({ agent_prompt: "Some prompt text" });
    const { container } = render(<AgentLogPanel agent={agent} onClose={vi.fn()} />);

    // Open the details
    const summary = screen.getByText(/Agent Prompt/);
    fireEvent.click(summary);

    const details = container.querySelector("details.agent-log-panel-prompt") as HTMLDetailsElement;
    expect(details.open).toBe(true);

    // Click the close button
    const closeBtn = screen.getByTitle("Collapse prompt");
    fireEvent.click(closeBtn);

    expect(details.open).toBe(false);
  });

  it("does not render prompt section when agent has no prompt", () => {
    const agent = mkAgent({ agent_prompt: "" });
    render(<AgentLogPanel agent={agent} onClose={vi.fn()} />);

    expect(screen.queryByText(/Agent Prompt/)).not.toBeInTheDocument();
  });

  it("prompt details container has scrollable styling class", () => {
    const agent = mkAgent({ agent_prompt: "x\n".repeat(200) });
    const { container } = render(<AgentLogPanel agent={agent} onClose={vi.fn()} />);

    // Open the prompt
    const summary = screen.getByText(/Agent Prompt/);
    fireEvent.click(summary);

    const detailsContent = container.querySelector(".agent-log-panel-prompt .log-accordion-details");
    expect(detailsContent).toBeInTheDocument();
  });
});
