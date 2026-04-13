import { describe, expect, it } from "vitest";

import type { AgentInfo } from "../types";
import { buildFlowchartData, inferCurrentStage, stageIcon } from "./agentFlowchart";

function makeAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    agent_id: "agent-1",
    name: "Test Agent",
    iteration: 1,
    status: "running",
    recent_logs: [],
    modified_files: [],
    ...overrides,
  };
}

describe("inferCurrentStage", () => {
  it("returns 'failed' for failed agents", () => {
    expect(inferCurrentStage(makeAgent({ status: "failed" }))).toBe("failed");
  });

  it("returns 'completed' for success agents", () => {
    expect(inferCurrentStage(makeAgent({ status: "success" }))).toBe("completed");
  });

  it("returns 'ai_invocation' when agent has modified files", () => {
    expect(
      inferCurrentStage(makeAgent({ modified_files: ["src/foo.ts"] })),
    ).toBe("ai_invocation");
  });

  it("returns 'ai_invocation' when agent has logs", () => {
    expect(
      inferCurrentStage(makeAgent({ recent_logs: ["Starting work..."] })),
    ).toBe("ai_invocation");
  });

  it("returns 'worktree' when agent has work_item_id but no logs", () => {
    expect(
      inferCurrentStage(makeAgent({ work_item_id: "task-123" })),
    ).toBe("worktree");
  });

  it("returns 'claim' for a brand new running agent with no data", () => {
    expect(inferCurrentStage(makeAgent())).toBe("claim");
  });
});

describe("buildFlowchartData", () => {
  it("builds a simple single-attempt flowchart for a running agent", () => {
    const agent = makeAgent({
      agent_id: "a1",
      status: "running",
      recent_logs: ["Working..."],
      work_item_id: "task-1",
    });

    const result = buildFlowchartData(agent, [agent]);

    expect(result.agentId).toBe("a1");
    expect(result.totalAttempts).toBe(1);
    // claim, worktree, ai, validation (no terminal yet since running)
    expect(result.nodes.length).toBe(4);
    expect(result.nodes[0].stage).toBe("claim");
    expect(result.nodes[0].status).toBe("done");
    expect(result.nodes[2].stage).toBe("ai_invocation");
    expect(result.nodes[2].status).toBe("active");
    expect(result.edges.length).toBe(3);
  });

  it("builds a completed agent flowchart with terminal node", () => {
    const agent = makeAgent({
      agent_id: "a1",
      status: "success",
      recent_logs: ["Done"],
      work_item_id: "task-1",
      modified_files: ["src/file.ts"],
    });

    const result = buildFlowchartData(agent, [agent]);

    expect(result.totalAttempts).toBe(1);
    // claim + worktree + ai + validation + completed
    expect(result.nodes.length).toBe(5);
    expect(result.nodes[4].stage).toBe("completed");
    expect(result.nodes[4].status).toBe("done");
  });

  it("builds a failed agent flowchart with failed terminal node", () => {
    const agent = makeAgent({
      agent_id: "a1",
      status: "failed",
      work_item_id: "task-1",
    });

    const result = buildFlowchartData(agent, [agent]);

    const failedNode = result.nodes.find((n) => n.stage === "failed");
    expect(failedNode).toBeDefined();
    expect(failedNode?.label).toBe("Failed");
  });

  it("builds a multi-attempt flowchart with retry chain", () => {
    const root = makeAgent({
      agent_id: "a1",
      card_id: "card-1",
      status: "failed",
      work_item_id: "task-1",
    });
    const gateForRoot = makeAgent({
      agent_id: "a1-gate",
      card_id: "card-1-gate",
      parent_card_id: "card-1",
      status: "failed",
      name: "gate",
    });
    const retry = makeAgent({
      agent_id: "a2",
      card_id: "card-2",
      parent_card_id: "card-1",
      status: "success",
      iteration: 2,
      work_item_id: "task-1",
      recent_logs: ["Retrying..."],
      modified_files: ["src/fix.ts"],
    });
    const gateForRetry = makeAgent({
      agent_id: "a2-gate",
      card_id: "card-2-gate",
      parent_card_id: "card-2",
      status: "success",
      name: "gate",
    });

    const allAgents = [root, gateForRoot, retry, gateForRetry];
    const result = buildFlowchartData(root, allAgents);

    expect(result.totalAttempts).toBe(2);
    // Attempt 1: claim+worktree+ai+validation+retry = 5
    // Attempt 2: claim+worktree+ai+validation+completed = 5
    expect(result.nodes.length).toBe(10);

    // Find retry node from attempt 1
    const retryNode = result.nodes.find((n) => n.stage === "retry");
    expect(retryNode).toBeDefined();
    expect(retryNode?.detail).toBe("With corrective feedback");

    // Find completed node from attempt 2
    const completedNode = result.nodes.find((n) => n.stage === "completed");
    expect(completedNode).toBeDefined();

    // Check retry edge exists
    const retryEdge = result.edges.find((e) => e.label === "Feedback");
    expect(retryEdge).toBeDefined();
  });

  it("includes gate agent status detail in validation node", () => {
    const agent = makeAgent({
      agent_id: "a1",
      card_id: "card-1",
      status: "success",
      work_item_id: "task-1",
      modified_files: ["f.ts"],
      recent_logs: ["done"],
    });
    const gate = makeAgent({
      agent_id: "a1-gate",
      card_id: "card-1-gate",
      parent_card_id: "card-1",
      status: "success",
      name: "gate",
    });

    const result = buildFlowchartData(agent, [agent, gate]);

    const validationNode = result.nodes.find((n) => n.stage === "validation");
    expect(validationNode?.detail).toBe("Passed ✓");
  });
});

describe("stageIcon", () => {
  it("returns expected icons", () => {
    expect(stageIcon("claim")).toBe("📋");
    expect(stageIcon("worktree")).toBe("🌳");
    expect(stageIcon("ai_invocation")).toBe("🤖");
    expect(stageIcon("validation")).toBe("🔍");
    expect(stageIcon("completed")).toBe("✅");
    expect(stageIcon("failed")).toBe("❌");
    expect(stageIcon("retry")).toBe("↻");
  });
});
