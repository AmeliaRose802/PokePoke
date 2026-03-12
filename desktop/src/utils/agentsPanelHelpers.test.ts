/**
 * Tests for agentsPanelHelpers retry cycle utilities.
 */

import { describe, expect, it } from "vitest";

import type { AgentInfo } from "../types";
import { collectAllGateDescendants, getCleanupChildren, getRetryChildren, shouldShowAttemptLabel } from "./agentsPanelHelpers";

function mkAgent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  const iteration = overrides.iteration ?? 1;
  const agentId = overrides.agent_id ?? "agent-1";
  return {
    agent_id: agentId,
    base_agent_id: overrides.base_agent_id ?? agentId,
    card_id: overrides.card_id ?? `${agentId}::v${iteration}`,
    parent_card_id: overrides.parent_card_id,
    name: "Worker",
    iteration,
    status: "running",
    recent_logs: [],
    is_history_entry: overrides.is_history_entry ?? false,
    ...overrides,
  };
}

describe("agentsPanelHelpers retry cycle utilities", () => {
  describe("collectAllGateDescendants", () => {
    it("returns empty array when no children", () => {
      const agent = mkAgent();
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(collectAllGateDescendants(agent, childrenMap)).toEqual([]);
    });

    it("returns direct gate children", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const gate = mkAgent({
        agent_id: "work-1-gate",
        card_id: "work-1-gate::v1",
        name: "Gate",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [gate]]]);
      const result = collectAllGateDescendants(parent, childrenMap);
      expect(result).toHaveLength(1);
      expect(result[0].agent_id).toBe("work-1-gate");
    });

    it("collects gate descendants from nested retry children", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const directGate = mkAgent({
        agent_id: "work-1-gate",
        card_id: "work-1-gate::v1",
        name: "Gate",
        status: "failed",
      });
      const retry = mkAgent({
        agent_id: "work-1-retry-2",
        card_id: "work-1-retry-2::v2",
        iteration: 2,
        parent_card_id: "work-1::v1",
      });
      const retryGate = mkAgent({
        agent_id: "work-1-retry-2-gate",
        card_id: "work-1-retry-2-gate::v2",
        name: "Gate",
        status: "success",
      });

      const childrenMap = new Map<string, AgentInfo[]>([
        ["work-1::v1", [directGate, retry]],
        ["work-1-retry-2::v2", [retryGate]],
      ]);

      const result = collectAllGateDescendants(parent, childrenMap);
      expect(result).toHaveLength(2);
      expect(result.map((a) => a.agent_id)).toEqual(["work-1-gate", "work-1-retry-2-gate"]);
    });
  });

  describe("getRetryChildren", () => {
    it("returns empty when no children", () => {
      const agent = mkAgent();
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(getRetryChildren(agent, childrenMap)).toEqual([]);
    });

    it("excludes gate agents", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const gate = mkAgent({
        agent_id: "work-1-gate",
        name: "Gate",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [gate]]]);
      expect(getRetryChildren(parent, childrenMap)).toEqual([]);
    });

    it("excludes maintenance sub-agents (parent_agent_id only)", () => {
      const parent = mkAgent({ agent_id: "janitor-1", card_id: "janitor-1::v1" });
      const sub = mkAgent({
        agent_id: "merge-conflict-1",
        name: "Merge Conflict",
        parent_agent_id: "janitor-1",
        // No parent_card_id — maintenance sub-agent
      });
      const childrenMap = new Map<string, AgentInfo[]>([["janitor-1", [sub]]]);
      expect(getRetryChildren(parent, childrenMap)).toEqual([]);
    });

    it("returns retry children (non-gate with parent_card_id)", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const retry = mkAgent({
        agent_id: "work-1-retry-2",
        card_id: "work-1-retry-2::v2",
        iteration: 2,
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [retry]]]);
      const result = getRetryChildren(parent, childrenMap);
      expect(result).toHaveLength(1);
      expect(result[0].agent_id).toBe("work-1-retry-2");
    });

    it("excludes cleanup agents (distinct workflow phase)", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const cleanup = mkAgent({
        agent_id: "cleanup-1",
        name: "Merge Conflict Cleanup",
        agent_type: "merge_conflict_cleanup",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [cleanup]]]);
      expect(getRetryChildren(parent, childrenMap)).toEqual([]);
    });
  });

  describe("getCleanupChildren", () => {
    it("returns empty when no children", () => {
      const agent = mkAgent();
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(getCleanupChildren(agent, childrenMap)).toEqual([]);
    });

    it("returns cleanup agents with parent_card_id", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const cleanup = mkAgent({
        agent_id: "cleanup-1",
        name: "Merge Conflict Cleanup",
        agent_type: "merge_conflict_cleanup",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [cleanup]]]);
      const result = getCleanupChildren(parent, childrenMap);
      expect(result).toHaveLength(1);
      expect(result[0].agent_id).toBe("cleanup-1");
    });

    it("excludes gate agents", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const gate = mkAgent({
        agent_id: "work-1-gate",
        name: "Gate",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [gate]]]);
      expect(getCleanupChildren(parent, childrenMap)).toEqual([]);
    });

    it("excludes work retry agents", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const retry = mkAgent({
        agent_id: "work-1-retry-2",
        iteration: 2,
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [retry]]]);
      expect(getCleanupChildren(parent, childrenMap)).toEqual([]);
    });

    it("excludes cleanup agents without parent_card_id", () => {
      const parent = mkAgent({ agent_id: "janitor-1", card_id: "janitor-1::v1" });
      const sub = mkAgent({
        agent_id: "cleanup-1",
        name: "Merge Conflict Cleanup",
        agent_type: "merge_conflict_cleanup",
        parent_agent_id: "janitor-1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["janitor-1", [sub]]]);
      expect(getCleanupChildren(parent, childrenMap)).toEqual([]);
    });
  });

  describe("shouldShowAttemptLabel", () => {
    it("returns false for gate agents", () => {
      const gate = mkAgent({ agent_id: "work-1-gate", name: "Gate" });
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(shouldShowAttemptLabel(gate, childrenMap)).toBe(false);
    });

    it("returns true for retry children (parent_card_id set)", () => {
      const retry = mkAgent({
        agent_id: "work-1-retry-2",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(shouldShowAttemptLabel(retry, childrenMap)).toBe(true);
    });

    it("returns true for root of retry cycle (has retry children)", () => {
      const parent = mkAgent({ agent_id: "work-1", card_id: "work-1::v1" });
      const retry = mkAgent({
        agent_id: "work-1-retry-2",
        parent_card_id: "work-1::v1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["work-1::v1", [retry]]]);
      expect(shouldShowAttemptLabel(parent, childrenMap)).toBe(true);
    });

    it("returns true for in-place resumed agents (iteration > 1, no parent_card_id)", () => {
      const resumed = mkAgent({
        agent_id: "work-1",
        iteration: 2,
        // No parent_card_id — timeout retry resumed in-place
      });
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(shouldShowAttemptLabel(resumed, childrenMap)).toBe(true);
    });

    it("returns false for standalone agents without retry cycle", () => {
      const agent = mkAgent({ agent_id: "standalone-1" });
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(shouldShowAttemptLabel(agent, childrenMap)).toBe(false);
    });

    it("returns false for maintenance parent with sub-agents (no parent_card_id)", () => {
      const janitor = mkAgent({ agent_id: "janitor-1", card_id: "janitor-1::v1" });
      const sub = mkAgent({
        agent_id: "merge-1",
        name: "Merge Cleanup",
        parent_agent_id: "janitor-1",
      });
      const childrenMap = new Map<string, AgentInfo[]>([["janitor-1", [sub]]]);
      expect(shouldShowAttemptLabel(janitor, childrenMap)).toBe(false);
    });

    it("returns false for cleanup agents even with parent_card_id", () => {
      const cleanup = mkAgent({
        agent_id: "cleanup-1",
        agent_type: "merge_conflict_cleanup",
        name: "Merge Conflict Cleanup",
        parent_card_id: "work-1::v1",
        iteration: 1,
      });
      const childrenMap = new Map<string, AgentInfo[]>();
      expect(shouldShowAttemptLabel(cleanup, childrenMap)).toBe(false);
    });
  });
});
