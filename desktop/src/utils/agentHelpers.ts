import type { AgentInfo } from "../types";
import { getAgentSnakeIcon } from "./snakeIcons";

const GATE_SUFFIX = "-gate";

function normalize(value: string | undefined | null): string {
  return value?.toLowerCase() ?? "";
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

/**
 * Get the snake icon path for an agent, or null if the agent doesn't have a work item ID
 */
export function getAgentAvatar(agent: AgentInfo): string | null {
  if (!agent.work_item_id) {
    // For agents without work items (maintenance agents, etc.), return null to use emoji fallback
    return null;
  }
  
  return getAgentSnakeIcon(agent.work_item_id, isGateAgent(agent));
}
