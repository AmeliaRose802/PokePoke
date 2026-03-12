import { describe, expect, it } from "vitest";

import type { AgentInfo } from "../types";
import { formatModelName, getAgentAvatar, getAgentType, getCleanupDisplayLabel, isCleanupAgent } from "./agentHelpers";
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

  describe("isCleanupAgent", () => {
    it("returns true for cleanup agent type", () => {
      expect(isCleanupAgent(mkAgent({ agent_type: "cleanup" }))).toBe(true);
    });

    it("returns true for code_conflict (merge conflict cleanup)", () => {
      expect(isCleanupAgent(mkAgent({ agent_type: "merge_conflict_cleanup" }))).toBe(true);
    });

    it("returns true for janitor agent type", () => {
      expect(isCleanupAgent(mkAgent({ agent_type: "janitor" }))).toBe(true);
    });

    it("returns true for tech_debt agent type", () => {
      expect(isCleanupAgent(mkAgent({ agent_type: "tech_debt" }))).toBe(true);
    });

    it("returns false for gate agents", () => {
      expect(isCleanupAgent(mkAgent({ agent_id: "work-1-gate", name: "Gate" }))).toBe(false);
    });

    it("returns false for work agents (no recognized type)", () => {
      expect(isCleanupAgent(mkAgent({ agent_type: "work" }))).toBe(false);
    });

    it("returns false for agents with no type", () => {
      expect(isCleanupAgent(mkAgent())).toBe(false);
    });
  });

  describe("getCleanupDisplayLabel", () => {
    it("returns 'Merge Conflict Cleanup' for code_conflict type", () => {
      const agent = mkAgent({ agent_type: "merge_conflict_cleanup" });
      expect(getCleanupDisplayLabel(agent)).toBe("Merge Conflict Cleanup");
    });

    it("returns 'Cleanup' for cleanup type", () => {
      const agent = mkAgent({ agent_type: "cleanup" });
      expect(getCleanupDisplayLabel(agent)).toBe("Cleanup");
    });

    it("returns 'Janitor' for janitor type", () => {
      const agent = mkAgent({ agent_type: "janitor" });
      expect(getCleanupDisplayLabel(agent)).toBe("Janitor");
    });

    it("falls back to agent name for unknown type", () => {
      const agent = mkAgent({ name: "Custom Cleanup", agent_type: undefined });
      expect(getCleanupDisplayLabel(agent)).toBe("Custom Cleanup");
    });
  });

  it("falls back to snake icon for work item agents without type", () => {
    const workItemId = "PP-123";
    const agent = mkAgent({ work_item_id: workItemId, agent_id: "work-pp-123" });
    expect(getAgentAvatar(agent)).toBe(getAgentSnakeIcon(workItemId, false));
  });

  describe("formatModelName", () => {
    it("formats Claude models with version numbers", () => {
      expect(formatModelName("claude-3-5-sonnet-20241022")).toBe("Claude Sonnet 3.5");
      expect(formatModelName("claude-3-haiku-20240307")).toBe("Claude Haiku 3");
      expect(formatModelName("claude-3-opus-20240229")).toBe("Claude Opus 3");
      expect(formatModelName("claude-opus-4.6")).toBe("Claude Opus 4.6");
      expect(formatModelName("claude-sonnet-4.5")).toBe("Claude Sonnet 4.5");
      expect(formatModelName("claude-unknown")).toBe("Claude");
      expect(formatModelName("claude-4")).toBe("Claude 4");
      expect(formatModelName("claude-2")).toBe("Claude 2");
    });

    it("formats GPT models with version numbers", () => {
      expect(formatModelName("gpt-4o")).toBe("GPT-4o");
      expect(formatModelName("gpt-4-turbo")).toBe("GPT-4 Turbo");
      expect(formatModelName("gpt-4")).toBe("GPT-4");
      expect(formatModelName("gpt-3.5-turbo")).toBe("GPT-3.5 Turbo");
      expect(formatModelName("gpt-5.3-codex")).toBe("GPT-5.3 Codex");
      expect(formatModelName("gpt-5.2")).toBe("GPT-5.2");
      expect(formatModelName("gpt-unknown")).toBe("GPT");
    });

    it("formats Gemini models with version numbers", () => {
      expect(formatModelName("gemini-1.5-pro")).toBe("Gemini 1.5 Pro");
      expect(formatModelName("gemini-2.0-flash")).toBe("Gemini 2.0 Flash");
      expect(formatModelName("gemini-flash")).toBe("Gemini Flash");
      expect(formatModelName("gemini-pro")).toBe("Gemini Pro");
    });

    it("handles null and undefined models", () => {
      expect(formatModelName(null)).toBe("Unknown Model");
      expect(formatModelName(undefined)).toBe("Unknown Model");
      expect(formatModelName("")).toBe("Unknown Model");
    });

    it("capitalizes unknown model names", () => {
      expect(formatModelName("custom-model-v1")).toBe("Custom-model-v1");
      expect(formatModelName("llama2")).toBe("Llama2");
    });
  });
});
