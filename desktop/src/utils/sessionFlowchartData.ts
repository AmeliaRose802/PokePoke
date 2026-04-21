/**
 * Data model and transformation for the session-level pipeline flowchart.
 *
 * Transforms the flat AgentInfo[] array into a structured representation
 * of parallel work-item slots flowing through the orchestration pipeline:
 *   Orchestrator → Work Agent → Gate Agent → Merge → outcome
 */

import type { AgentInfo } from "../types";

/* ── Types ─────────────────────────────────────────────────────────────── */

export type StageStatus = "done" | "active" | "pending" | "failed";
export type SlotOutcome = "success" | "failed" | "deferred" | "decomposed" | "active";

/** A single pipeline stage within a work-item slot */
export interface PipelineStage {
  status: StageStatus;
  label: string;
  detail: string;
  duration: string | null;
  agentId: string;
  logs: string[];
}

/** A work-item slot in the session flowchart */
export interface FlowchartSlot {
  id: string;
  shortId: string;
  title: string | null;

  work: PipelineStage | null;
  gate: PipelineStage | null;
  merge: PipelineStage | null;
  cleanup: PipelineStage | null;
  retryMerge: PipelineStage | null;

  outcome: SlotOutcome;
  attempts: number;
  hasRetryArc: boolean;
}

/** Aggregated session flowchart data */
export interface SessionFlowchartData {
  completed: FlowchartSlot[];
  active: FlowchartSlot[];
  maintenance: PipelineStage[];

  merged: number;
  activeCount: number;
  deferred: number;
  decomposed: number;
  failed: number;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

const MAINTENANCE_TYPES = new Set([
  "worktree_cleanup",
  "backlog_cleanup",
  "tech_debt",
  "janitor",
  "beta_tester",
  "beta_test",
  "code_review",
  "worktree_cleanup_agent",
  "janitor_agent",
  "tech_debt_agent",
  "beta_tester_agent",
  "maintenance_janitor",
  "maintenance_tech_debt",
]);

function resolveAgentType(agent: AgentInfo): string {
  if (agent.agent_type) return agent.agent_type.toLowerCase().replace(/[^a-z0-9]+/g, "_");
  const name = (agent.name ?? "").toLowerCase();
  if (name.includes("gate")) return "gate";
  if (name.includes("cleanup") || name.includes("conflict")) return "cleanup";
  return "work";
}

function isMaintenance(agent: AgentInfo): boolean {
  const t = resolveAgentType(agent);
  return MAINTENANCE_TYPES.has(t);
}

function isGate(agent: AgentInfo): boolean {
  return resolveAgentType(agent) === "gate" ||
    (agent.agent_id ?? "").toLowerCase().endsWith("-gate") ||
    (agent.name ?? "").toLowerCase().includes("gate");
}

function isCleanup(agent: AgentInfo): boolean {
  const t = resolveAgentType(agent);
  return t === "cleanup" || t === "code_conflict" || t === "merge_conflict_cleanup";
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) return "<1s";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${s}s`;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function agentDuration(agent: AgentInfo): string | null {
  if (!agent.started_at) return null;
  const end = agent.last_updated ?? Date.now() / 1000;
  return formatDuration(end - agent.started_at);
}

function toStageStatus(s: string): StageStatus {
  if (s === "running") return "active";
  if (s === "success") return "done";
  if (s === "failed") return "failed";
  return "pending";
}

function shortId(id: string): string {
  const parts = id.split("-");
  return parts[parts.length - 1] ?? id;
}

function toStage(agent: AgentInfo, label: string): PipelineStage {
  const status = toStageStatus(agent.status);
  const dur = agentDuration(agent);
  let detail: string;
  if (status === "active") {
    detail = `● ${dur ?? "0s"}`;
  } else if (status === "done") {
    detail = `✓ ${dur ?? ""}`;
  } else if (status === "failed") {
    detail = `✗ ${dur ?? ""}`;
  } else {
    detail = "";
  }
  return {
    status,
    label,
    detail,
    duration: dur,
    agentId: agent.agent_id,
    logs: agent.recent_logs ?? [],
  };
}

/* ── Main transform ────────────────────────────────────────────────────── */

export function buildSessionFlowchart(
  agents: AgentInfo[],
  currentSessionId: string | null,
): SessionFlowchartData {
  // Filter to current session
  const sessionAgents = currentSessionId
    ? agents.filter((a) => a.session_id === currentSessionId || !a.session_id)
    : agents;

  const maintenanceList: AgentInfo[] = [];
  const workItemMap = new Map<string, AgentInfo[]>();

  for (const agent of sessionAgents) {
    if (isMaintenance(agent)) {
      maintenanceList.push(agent);
      continue;
    }
    const key = agent.work_item_id ?? agent.agent_id;
    const group = workItemMap.get(key) ?? [];
    group.push(agent);
    workItemMap.set(key, group);
  }

  const slots: FlowchartSlot[] = [];

  for (const [itemKey, itemAgents] of workItemMap) {
    // Find latest work agent (highest iteration or most recent)
    const workAgents = itemAgents
      .filter((a) => !isGate(a) && !isCleanup(a))
      .sort((a, b) => (b.iteration ?? 0) - (a.iteration ?? 0));
    const latestWork = workAgents[0] ?? null;

    // Find gate agent
    const gateAgents = itemAgents
      .filter((a) => isGate(a))
      .sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0));
    const latestGate = gateAgents[0] ?? null;

    // Find cleanup agent
    const cleanupAgent = itemAgents.find((a) => isCleanup(a)) ?? null;

    const isActive = itemAgents.some((a) => a.status === "running");
    const attempts = latestWork?.iteration ?? 1;

    // Determine outcome
    let outcome: SlotOutcome = "active";
    if (!isActive) {
      const gatePassed = latestGate?.status === "success";
      const gateFailed = latestGate?.status === "failed";
      const workFailed = latestWork?.status === "failed";

      if (gatePassed || (!latestGate && latestWork?.status === "success")) {
        outcome = "success";
      } else if (gateFailed && attempts >= 3) {
        outcome = "deferred";
      } else if (workFailed) {
        outcome = "failed";
      } else if (gateFailed) {
        outcome = "failed";
      } else {
        outcome = "success";
      }
    }

    // Build stages
    const workStage = latestWork ? toStage(latestWork, "Work Agent") : null;
    if (workStage && attempts > 1) {
      workStage.detail += ` · att. ${attempts}`;
    }

    let gateStage: PipelineStage | null = null;
    if (latestGate) {
      gateStage = toStage(latestGate, "Gate Agent");
      if (latestGate.status === "success") {
        gateStage.detail = `✓ Approved · ${agentDuration(latestGate) ?? ""}`;
      } else if (latestGate.status === "failed") {
        gateStage.detail = `✗ Rejected${attempts > 1 ? ` ×${attempts}` : ""}`;
      }
    }

    // Merge stage: inferred from outcome for completed items
    let mergeStage: PipelineStage | null = null;
    if (outcome === "success") {
      mergeStage = {
        status: "done",
        label: "🔒 Merge to main",
        detail: "✓ clean",
        duration: null,
        agentId: "",
        logs: [],
      };
    }

    const cleanupStage = cleanupAgent ? toStage(cleanupAgent, "Cleanup Agent") : null;
    const hasRetryArc = attempts > 1 && latestGate !== null;

    slots.push({
      id: itemKey,
      shortId: shortId(itemKey),
      title: latestWork?.work_item_title ?? null,
      work: workStage,
      gate: gateStage,
      merge: mergeStage,
      cleanup: cleanupStage,
      retryMerge: cleanupStage
        ? { status: "done", label: "🔒 Retry merge", detail: "✓ clean", duration: null, agentId: "", logs: [] }
        : null,
      outcome,
      attempts,
      hasRetryArc,
    });
  }

  const completed = slots.filter((s) => s.outcome !== "active");
  const active = slots.filter((s) => s.outcome === "active");

  const maintenance: PipelineStage[] = maintenanceList.map((a) => {
    const stage = toStage(a, a.name ?? resolveAgentType(a));
    return stage;
  });

  return {
    completed,
    active,
    maintenance,
    merged: completed.filter((s) => s.outcome === "success").length,
    activeCount: active.length,
    deferred: completed.filter((s) => s.outcome === "deferred").length,
    decomposed: completed.filter((s) => s.outcome === "decomposed").length,
    failed: completed.filter((s) => s.outcome === "failed").length,
  };
}
