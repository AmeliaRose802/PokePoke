/**
 * Tests for sessionFlowchartData utility functions.
 */

import { describe, expect, it } from "vitest";

import type { AgentInfo } from "../types";
import { buildSessionFlowchart, formatDuration } from "./sessionFlowchartData";

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

describe("formatDuration", () => {
  it("formats seconds only", () => {
    expect(formatDuration(42)).toBe("42s");
  });

  it("formats minutes and seconds", () => {
    expect(formatDuration(125)).toBe("2m 05s");
  });

  it("formats sub-second as <1s", () => {
    expect(formatDuration(0.3)).toBe("<1s");
  });
});

describe("buildSessionFlowchart", () => {
  it("returns empty data when no agents", () => {
    const data = buildSessionFlowchart([], null);
    expect(data.completed).toHaveLength(0);
    expect(data.active).toHaveLength(0);
    expect(data.maintenance).toHaveLength(0);
    expect(data.merged).toBe(0);
    expect(data.activeCount).toBe(0);
  });

  it("classifies a running work agent as active", () => {
    const agent = mkAgent({
      agent_id: "w1",
      status: "running",
      work_item_id: "item-1",
      work_item_title: "Fix bug",
    });
    const data = buildSessionFlowchart([agent], null);
    expect(data.active).toHaveLength(1);
    expect(data.active[0].id).toBe("item-1");
    expect(data.active[0].work?.status).toBe("active");
    expect(data.active[0].outcome).toBe("active");
  });

  it("classifies a successful work + gate as completed/merged", () => {
    const work = mkAgent({
      agent_id: "w1",
      status: "success",
      work_item_id: "item-1",
      started_at: 1000,
      last_updated: 1060,
    });
    const gate = mkAgent({
      agent_id: "w1-gate",
      name: "gate",
      status: "success",
      work_item_id: "item-1",
      started_at: 1060,
      last_updated: 1100,
    });
    const data = buildSessionFlowchart([work, gate], null);
    expect(data.completed).toHaveLength(1);
    expect(data.completed[0].outcome).toBe("success");
    expect(data.merged).toBe(1);
    expect(data.active).toHaveLength(0);
  });

  it("classifies a gate-rejected item after 3 attempts as deferred", () => {
    const work = mkAgent({
      agent_id: "w1",
      status: "success",
      work_item_id: "item-1",
      iteration: 3,
    });
    const gate = mkAgent({
      agent_id: "w1-gate",
      name: "gate",
      status: "failed",
      work_item_id: "item-1",
    });
    const data = buildSessionFlowchart([work, gate], null);
    expect(data.completed).toHaveLength(1);
    expect(data.completed[0].outcome).toBe("deferred");
    expect(data.deferred).toBe(1);
  });

  it("classifies maintenance agents separately", () => {
    const maint = mkAgent({
      agent_id: "m1",
      name: "Worktree Cleanup",
      status: "success",
      agent_type: "worktree_cleanup",
    });
    const work = mkAgent({
      agent_id: "w1",
      status: "running",
      work_item_id: "item-1",
    });
    const data = buildSessionFlowchart([maint, work], null);
    // Maintenance agents are now included in completed/active, not a separate array
    expect(data.maintenance).toHaveLength(0);
    expect(data.active).toHaveLength(1);
    expect(data.completed).toHaveLength(1);
    // Maintenance slot should be in completed
    const maintSlot = data.completed.find((s) => s.id === "m1");
    expect(maintSlot).toBeDefined();
    expect(maintSlot?.isMaintenance).toBe(true);
    expect(maintSlot?.work?.label).toBe("Worktree Cleanup");
  });

  it("includes running maintenance agents in activeCount", () => {
    const maint = mkAgent({
      agent_id: "m1",
      name: "Tech Debt Agent",
      status: "running",
      agent_type: "tech_debt_agent",
    });
    const work1 = mkAgent({
      agent_id: "w1",
      status: "running",
      work_item_id: "item-1",
    });
    const work2 = mkAgent({
      agent_id: "w2",
      status: "running",
      work_item_id: "item-2",
    });
    const data = buildSessionFlowchart([maint, work1, work2], null);
    // activeCount should include maintenance agent + 2 work agents = 3
    expect(data.activeCount).toBe(3);
    expect(data.active).toHaveLength(3);
    // Find the maintenance slot
    const maintSlot = data.active.find((s) => s.isMaintenance);
    expect(maintSlot).toBeDefined();
    expect(maintSlot?.work?.label).toBe("Tech Debt Agent");
  });

  it("groups agents by work_item_id", () => {
    const w1 = mkAgent({ agent_id: "a1", status: "success", work_item_id: "item-1" });
    const g1 = mkAgent({ agent_id: "a1-gate", name: "gate", status: "success", work_item_id: "item-1" });
    const w2 = mkAgent({ agent_id: "a2", status: "running", work_item_id: "item-2" });
    const data = buildSessionFlowchart([w1, g1, w2], null);
    expect(data.completed).toHaveLength(1);
    expect(data.active).toHaveLength(1);
  });

  it("filters agents by session_id when provided", () => {
    const a1 = mkAgent({ agent_id: "a1", status: "running", session_id: "s1", work_item_id: "i1" });
    const a2 = mkAgent({ agent_id: "a2", status: "running", session_id: "s2", work_item_id: "i2" });
    const data = buildSessionFlowchart([a1, a2], "s1");
    expect(data.active).toHaveLength(1);
    expect(data.active[0].id).toBe("i1");
  });

  it("marks retry arc when gate rejected and iteration > 1", () => {
    const work = mkAgent({
      agent_id: "w1",
      status: "running",
      work_item_id: "item-1",
      iteration: 2,
    });
    const gate = mkAgent({
      agent_id: "w1-gate",
      name: "gate",
      status: "failed",
      work_item_id: "item-1",
    });
    const data = buildSessionFlowchart([work, gate], null);
    expect(data.active).toHaveLength(1);
    expect(data.active[0].hasRetryArc).toBe(true);
    expect(data.active[0].attempts).toBe(2);
  });
});
