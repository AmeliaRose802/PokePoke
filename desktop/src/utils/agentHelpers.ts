import type { AgentInfo } from "../types";
import { getAgentSnakeIcon } from "./snakeIcons";

const GATE_SUFFIX = "-gate";

const AGENT_ICON_MAP: Record<string, string> = {
  beta_test: "/agent_icons/beta_test_agent_icon.png",
  cleanup: "/agent_icons/cleanup_agent_icon.png",
  code_conflict: "/agent_icons/code_conflict_agent_icon.png",
  gate: "/agent_icons/gate_agent_icon.png",
  janitor: "/agent_icons/janitor_agent_icon.png",
  tech_debt: "/agent_icons/tech_debt_agent_icon.png",
  worktree_cleanup: "/agent_icons/worktree_cleanup_agent_icon.png",
};

const AGENT_TYPE_ALIASES: Record<string, string> = {
  beta_tester: "beta_test",
  beta_tester_agent: "beta_test",
  beta_test_agent: "beta_test",
  cleanup_agent: "cleanup",
  merge_conflict_cleanup: "code_conflict",
  merge_conflict: "code_conflict",
  code_conflict_agent: "code_conflict",
  janitor_agent: "janitor",
  maintenance_janitor: "janitor",
  tech_debt_agent: "tech_debt",
  techdebt: "tech_debt",
  maintenance_tech_debt: "tech_debt",
  worktree_cleanup_agent: "worktree_cleanup",
  worktreecleanup: "worktree_cleanup",
};

function normalize(value: string | undefined | null): string {
  return value?.toLowerCase() ?? "";
}

function normalizeAgentTypeCandidate(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!normalized) return null;
  const withoutMaintenancePrefix = normalized.startsWith("maintenance_")
    ? normalized.replace(/^maintenance_/, "")
    : normalized;
  return AGENT_TYPE_ALIASES[withoutMaintenancePrefix] ?? withoutMaintenancePrefix;
}

export function isGateAgent(agent: AgentInfo): boolean {
  const normalizedId = normalize(agent.agent_id);
  const normalizedName = normalize(agent.name);
  return normalizedId.endsWith(GATE_SUFFIX) || normalizedName.includes("gate");
}

export function getAgentPrimaryLabel(agent: AgentInfo): string {
  if (agent.work_item_id) {
    return agent.work_item_title
      ? `${agent.work_item_id}: ${agent.work_item_title}`
      : agent.work_item_id;
  }
  return agent.name;
}

export function getAgentType(agent: AgentInfo): string | null {
  if (isGateAgent(agent)) {
    return "gate";
  }

  const candidates = [agent.agent_type, agent.agent_id, agent.name];
  for (const candidate of candidates) {
    const normalized = normalizeAgentTypeCandidate(candidate);
    if (normalized && AGENT_ICON_MAP[normalized]) {
      return normalized;
    }
  }
  return null;
}

/**
 * Get the snake icon path for an agent, or null if the agent doesn't have a work item ID
 */
export function getAgentAvatar(agent: AgentInfo): string | null {
  const agentType = getAgentType(agent);
  if (agentType) {
    return AGENT_ICON_MAP[agentType];
  }

  if (!agent.work_item_id) {
    return null;
  }

  return getAgentSnakeIcon(agent.work_item_id, isGateAgent(agent));
}

/**
 * Format a model name into a user-friendly display name.
 * Converts technical model names into readable labels.
 */
export function formatModelName(model: string | null | undefined): string {
  if (!model) {
    return "Unknown Model";
  }

  const modelStr = model.toLowerCase();

  // Claude models
  if (modelStr.includes("claude")) {
    if (modelStr.includes("sonnet")) {
      return "Claude Sonnet";
    } else if (modelStr.includes("haiku")) {
      return "Claude Haiku";
    } else if (modelStr.includes("opus")) {
      return "Claude Opus";
    }
    return "Claude";
  }

  // GPT models
  if (modelStr.includes("gpt")) {
    if (modelStr.includes("4o")) {
      return "GPT-4o";
    } else if (modelStr.includes("4") && modelStr.includes("turbo")) {
      return "GPT-4 Turbo";
    } else if (modelStr.includes("4")) {
      return "GPT-4";
    } else if (modelStr.includes("3.5")) {
      return "GPT-3.5";
    }
    return "GPT";
  }

  // Gemini models
  if (modelStr.includes("gemini")) {
    if (modelStr.includes("pro")) {
      return "Gemini Pro";
    }
    return "Gemini";
  }

  // For any other model, capitalize the first letter and return as-is
  return model.charAt(0).toUpperCase() + model.slice(1);
}
