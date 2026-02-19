import type { AgentInfo } from "../types";

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
