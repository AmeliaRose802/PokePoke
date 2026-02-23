import type { AgentInfo } from "../types";

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
