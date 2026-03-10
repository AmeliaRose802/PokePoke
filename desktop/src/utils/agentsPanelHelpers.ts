import type { AgentInfo } from "../types";
import { isGateAgent } from "./agentHelpers";

const ROBOT_AVATARS = [
  "🐍", "🦎", "🕷️", "🦇", "🦋", "🐛", "🐝", "🐞",
  "🤖", "🔧", "⚡", "🎯", "🔮", "🎲", "🔬", "🧩",
];

/** Deterministic avatar based on agent_id hash (fallback for agents without work items) */
export function getEmojiAvatar(agentId: string): string {
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = ((hash << 5) - hash + agentId.charCodeAt(i)) | 0;
  }
  return ROBOT_AVATARS[Math.abs(hash) % ROBOT_AVATARS.length];
}

export const STATUS_INDICATOR: Record<string, { dot: string; label: string }> = {
  running: { dot: "agent-dot-running", label: "Running" },
  success: { dot: "agent-dot-success", label: "Done" },
  failed: { dot: "agent-dot-failed", label: "Failed" },
};

export const GATE_STATUS_COPY: Record<AgentInfo["status"], string> = {
  running: "Gate running",
  success: "Gate passed",
  failed: "Gate failed",
};

export const UNKNOWN_SESSION = "__unknown__";

/** Format a session_id (epoch timestamp string) as a readable label. */
export function formatSessionLabel(sessionId: string): string {
  if (sessionId === UNKNOWN_SESSION) return "Previous Session";
  const epoch = parseFloat(sessionId);
  if (isNaN(epoch)) return `Session ${sessionId}`;
  const date = new Date(epoch * 1000);
  const ymd = date.toLocaleDateString(undefined, { year: "numeric", month: "2-digit", day: "2-digit" });
  const hm = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `Session ${ymd} ${hm}`;
}

/** Group agents by session_id, preserving order (most recent last). */
export function groupBySession(
  agents: AgentInfo[]
): { sessionId: string; agents: AgentInfo[] }[] {
  const map = new Map<string, AgentInfo[]>();
  for (const agent of agents) {
    const sid = agent.session_id ?? UNKNOWN_SESSION;
    const group = map.get(sid);
    if (group) {
      group.push(agent);
    } else {
      map.set(sid, [agent]);
    }
  }
  return Array.from(map.entries()).map(([sessionId, sessionAgents]) => ({
    sessionId,
    agents: sessionAgents,
  }));
}

export const cardIdForAgent = (agent: AgentInfo): string =>
  agent.card_id ?? agent.agent_id;

export const parentKeysForAgent = (agent: AgentInfo): string[] => {
  const keys: string[] = [];
  if (agent.parent_card_id) {
    keys.push(agent.parent_card_id);
  }
  if (agent.parent_agent_id) {
    keys.push(agent.parent_agent_id);
  }
  return keys;
};

export const isHistoryAgent = (agent: AgentInfo): boolean =>
  agent.is_history_entry === true;

/**
 * Recursively collect all gate agent descendants in a subtree.
 * Used to find the final gate verdict across all retry attempts.
 */
export function collectAllGateDescendants(
  agent: AgentInfo,
  childrenMap: Map<string, AgentInfo[]>
): AgentInfo[] {
  const key = cardIdForAgent(agent);
  const children =
    childrenMap.get(key) ?? childrenMap.get(agent.agent_id) ?? [];
  const gates: AgentInfo[] = [];
  for (const child of children) {
    if (isGateAgent(child)) {
      gates.push(child);
    }
    gates.push(...collectAllGateDescendants(child, childrenMap));
  }
  return gates;
}

/**
 * Get non-gate children that are retry agents (linked via parent_card_id).
 * Maintenance sub-agents use parent_agent_id, so they are excluded.
 */
export function getRetryChildren(
  agent: AgentInfo,
  childrenMap: Map<string, AgentInfo[]>
): AgentInfo[] {
  const key = cardIdForAgent(agent);
  const children =
    childrenMap.get(key) ?? childrenMap.get(agent.agent_id) ?? [];
  return children.filter((c) => !isGateAgent(c) && !!c.parent_card_id);
}

/**
 * Determine which gate agent to display on a card.
 * For root agents with retry children, traverses all descendants
 * to find the final (most recent) gate result.
 */
export function resolveGateForDisplay(
  agent: AgentInfo,
  childrenMap: Map<string, AgentInfo[]>
): { gate: AgentInfo | null; isRetryCycleRoot: boolean } {
  if (isGateAgent(agent)) return { gate: null, isRetryCycleRoot: false };

  const key = cardIdForAgent(agent);
  const directGates = (
    childrenMap.get(key) ?? childrenMap.get(agent.agent_id) ?? []
  ).filter(isGateAgent);
  const directGate = directGates.length > 0 ? directGates[directGates.length - 1] : null;

  const retries = getRetryChildren(agent, childrenMap);
  if (retries.length === 0) return { gate: directGate, isRetryCycleRoot: false };

  const allGates = collectAllGateDescendants(agent, childrenMap);
  const latest = allGates.length > 0
    ? allGates.sort((a, b) => (a.started_at ?? a.iteration) - (b.started_at ?? b.iteration))[allGates.length - 1]
    : null;
  return { gate: latest ?? directGate, isRetryCycleRoot: true };
}
export function shouldShowAttemptLabel(
  agent: AgentInfo,
  childrenMap: Map<string, AgentInfo[]>
): boolean {
  if (isGateAgent(agent)) return false;
  // Agent is a retry child (has parent_card_id and is not a gate)
  if (agent.parent_card_id) return true;
  // Agent is the root of a retry cycle (has non-gate children linked via parent_card_id)
  return getRetryChildren(agent, childrenMap).length > 0;
}
