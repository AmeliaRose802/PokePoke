import { describe, expect, it } from "vitest";

import type { AgentInfo } from "../types";
import { getAgentAvatar, getAgentType } from "./agentHelpers";
import { getAgentSnakeIcon } from "./snakeIcons";

function mkAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    agent_id: "agent-1",
    name: "Agent",
    iteration: 1,
    status: "running",
    recent_logs: [],
    ...overrides,
  };
}

describe("agentHelpers", () => {
  it("normalizes agent_type aliases to known types", () => {
    const agent = mkAgent({ agent_type: "tech-debt" });
    expect(getAgentType(agent)).toBe("tech_debt");
  });

  it("derives agent type from maintenance-prefixed agent IDs", () => {
    const agent = mkAgent({ agent_id: "maintenance-janitor-123", name: "Janitor Agent" });
    expect(getAgentType(agent)).toBe("janitor");
  });

  it("prioritizes gate detection for gate agents", () => {
    const agent = mkAgent({ agent_id: "work-123-gate", name: "Gate Agent" });
    expect(getAgentType(agent)).toBe("gate");
    expect(getAgentAvatar(agent)).toBe("/agent_icons/gate_agent_icon.png");
  });

  it("returns mapped icon when agent type matches", () => {
    const agent = mkAgent({ agent_type: "beta_test" });
    expect(getAgentAvatar(agent)).toBe("/agent_icons/beta_test_agent_icon.png");
  });

  it("falls back to snake icon for work item agents without type", () => {
    const workItemId = "PP-123";
    const agent = mkAgent({ work_item_id: workItemId, agent_id: "work-pp-123" });
    expect(getAgentAvatar(agent)).toBe(getAgentSnakeIcon(workItemId, false));
  });
});
