/**
 * Agent flowchart data model and stage derivation logic.
 *
 * Derives pipeline stages from AgentInfo data to visualize
 * agent progress through the orchestration pipeline.
 */

import type { AgentInfo } from "../types";
import { isCleanupAgent, isGateAgent } from "./agentHelpers";
import { cardIdForAgent } from "./agentsPanelHelpers";

/** Pipeline stage identifiers in execution order */
export type PipelineStage =
  | "claim"
  | "worktree"
  | "ai_invocation"
  | "validation"
  | "completed"
  | "failed"
  | "retry";

/** Visual status for a pipeline stage node */
export type StageStatus = "done" | "active" | "pending" | "skipped";

/** A single node in the flowchart */
export interface FlowchartNode {
  id: string;
  stage: PipelineStage;
  label: string;
  status: StageStatus;
  detail?: string;
  attempt?: number;
}

/** An edge connecting two flowchart nodes */
export interface FlowchartEdge {
  from: string;
  to: string;
  label?: string;
}

/** Complete flowchart data for rendering */
export interface FlowchartData {
  nodes: FlowchartNode[];
  edges: FlowchartEdge[];
  /** The primary agent this flowchart represents */
  agentId: string;
  /** Total retry attempts */
  totalAttempts: number;
}

/**
 * Determine the current pipeline stage for an agent based on its status
 * and available data.
 */
export function inferCurrentStage(agent: AgentInfo): PipelineStage {
  if (agent.status === "failed") return "failed";
  if (agent.status === "success") return "completed";

  // Running agent - infer stage from available data
  if (agent.modified_files && agent.modified_files.length > 0) {
    return "ai_invocation";
  }
  if (agent.recent_logs.length > 0 || (agent.log_lines && agent.log_lines.length > 0)) {
    return "ai_invocation";
  }

  // Very early stage — no logs yet
  if (agent.work_item_id) {
    return "worktree";
  }

  return "claim";
}

/**
 * Build a flowchart for a single agent and its retry/gate chain.
 *
 * @param agent - The root agent to visualize
 * @param allAgents - All agents in the session (to find gates and retries)
 */
export function buildFlowchartData(agent: AgentInfo, allAgents: AgentInfo[]): FlowchartData {
  // Build children map
  const childrenMap = new Map<string, AgentInfo[]>();
  for (const a of allAgents) {
    const parentKey = a.parent_card_id ?? a.parent_agent_id;
    if (parentKey) {
      const siblings = childrenMap.get(parentKey) ?? [];
      siblings.push(a);
      childrenMap.set(parentKey, siblings);
    }
  }

  const nodes: FlowchartNode[] = [];
  const edges: FlowchartEdge[] = [];

  // Collect the retry chain: root → retry1 → retry2 ...
  const retryChain = collectRetryChain(agent, childrenMap);
  const totalAttempts = retryChain.length;

  for (let attemptIdx = 0; attemptIdx < retryChain.length; attemptIdx++) {
    const attemptAgent = retryChain[attemptIdx];
    const attemptNum = attemptIdx + 1;
    const isLast = attemptIdx === retryChain.length - 1;
    const prefix = `a${attemptNum}`;
    const currentStage = inferCurrentStage(attemptAgent);

    // Claim stage
    const claimDone = true; // If agent exists, claim happened
    nodes.push({
      id: `${prefix}-claim`,
      stage: "claim",
      label: attemptNum > 1 ? `Retry #${attemptNum}` : "Task Claimed",
      status: "done",
      attempt: attemptNum,
    });

    // Worktree stage
    const worktreeDone = stageReached(currentStage, "worktree");
    nodes.push({
      id: `${prefix}-worktree`,
      stage: "worktree",
      label: "Worktree Setup",
      status: worktreeDone ? "done" : claimDone && isLast && attemptAgent.status === "running" ? "active" : "pending",
      attempt: attemptNum,
    });
    edges.push({ from: `${prefix}-claim`, to: `${prefix}-worktree` });

    // AI invocation stage
    const aiDone = stageReached(currentStage, "ai_invocation");
    const aiActive = currentStage === "ai_invocation" && attemptAgent.status === "running";
    nodes.push({
      id: `${prefix}-ai`,
      stage: "ai_invocation",
      label: "AI Working",
      status: aiActive ? "active" : aiDone ? "done" : "pending",
      detail: attemptAgent.model ?? undefined,
      attempt: attemptNum,
    });
    edges.push({ from: `${prefix}-worktree`, to: `${prefix}-ai` });

    // Find gate agent for this attempt
    const agentKey = cardIdForAgent(attemptAgent);
    const children = childrenMap.get(agentKey) ?? childrenMap.get(attemptAgent.agent_id) ?? [];
    const gateAgent = children.find(isGateAgent);

    // Validation stage
    const validationStatus = getValidationStatus(attemptAgent, gateAgent);
    nodes.push({
      id: `${prefix}-validation`,
      stage: "validation",
      label: "Quality Gate",
      status: validationStatus,
      detail: gateAgent ? gateStatusDetail(gateAgent) : undefined,
      attempt: attemptNum,
    });
    edges.push({ from: `${prefix}-ai`, to: `${prefix}-validation` });

    // Terminal stage for this attempt
    if (isLast) {
      if (currentStage === "completed") {
        nodes.push({
          id: `${prefix}-complete`,
          stage: "completed",
          label: "Completed",
          status: "done",
          attempt: attemptNum,
        });
        edges.push({ from: `${prefix}-validation`, to: `${prefix}-complete` });
      } else if (currentStage === "failed") {
        nodes.push({
          id: `${prefix}-failed`,
          stage: "failed",
          label: "Failed",
          status: "done",
          attempt: attemptNum,
        });
        edges.push({ from: `${prefix}-validation`, to: `${prefix}-failed` });
      }
      // If still running, no terminal node yet
    } else {
      // This attempt was retried - add retry edge to next attempt
      nodes.push({
        id: `${prefix}-retry`,
        stage: "retry",
        label: "Retried",
        status: "done",
        detail: "With corrective feedback",
        attempt: attemptNum,
      });
      edges.push({ from: `${prefix}-validation`, to: `${prefix}-retry` });
      edges.push({
        from: `${prefix}-retry`,
        to: `a${attemptNum + 1}-claim`,
        label: "Feedback",
      });
    }
  }

  return {
    nodes,
    edges,
    agentId: agent.agent_id,
    totalAttempts,
  };
}

/**
 * Collect the linear retry chain starting from a root agent.
 * Returns [rootAgent, retry1, retry2, ...] in chronological order.
 */
function collectRetryChain(root: AgentInfo, childrenMap: Map<string, AgentInfo[]>): AgentInfo[] {
  const chain: AgentInfo[] = [root];
  let current = root;

  while (true) {
    const key = cardIdForAgent(current);
    const children = childrenMap.get(key) ?? childrenMap.get(current.agent_id) ?? [];
    const retryChild = children.find(
      (c) => !isGateAgent(c) && !isCleanupAgent(c) && !!c.parent_card_id,
    );
    if (!retryChild) break;
    chain.push(retryChild);
    current = retryChild;
  }

  return chain;
}

const STAGE_ORDER: PipelineStage[] = [
  "claim",
  "worktree",
  "ai_invocation",
  "validation",
  "completed",
];

/** Check if the current stage has reached or passed the target stage */
function stageReached(current: PipelineStage, target: PipelineStage): boolean {
  const currentIdx = STAGE_ORDER.indexOf(current);
  const targetIdx = STAGE_ORDER.indexOf(target);
  if (currentIdx === -1 || targetIdx === -1) {
    // Failed/retry are terminal-ish; they've passed validation
    if (current === "failed" || current === "retry") {
      return targetIdx <= STAGE_ORDER.indexOf("validation");
    }
    return false;
  }
  return currentIdx >= targetIdx;
}

function getValidationStatus(agent: AgentInfo, gateAgent: AgentInfo | undefined): StageStatus {
  if (!gateAgent) {
    // No gate agent yet
    if (agent.status === "success") return "done";
    if (agent.status === "failed") return "done";
    return "pending";
  }
  if (gateAgent.status === "running") return "active";
  return "done";
}

function gateStatusDetail(gate: AgentInfo): string {
  if (gate.status === "running") return "Running checks…";
  if (gate.status === "success") return "Passed ✓";
  if (gate.status === "failed") return "Failed ✗";
  return "";
}

/** Get a human-readable label for a pipeline stage */
export function stageIcon(stage: PipelineStage): string {
  switch (stage) {
    case "claim":
      return "📋";
    case "worktree":
      return "🌳";
    case "ai_invocation":
      return "🤖";
    case "validation":
      return "🔍";
    case "completed":
      return "✅";
    case "failed":
      return "❌";
    case "retry":
      return "↻";
    default:
      return "•";
  }
}
