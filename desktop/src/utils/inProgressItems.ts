import type { AgentInfo } from "../types";
import { isHistoryAgent } from "./agentsPanelHelpers";

interface InProgressAgent {
  name: string;
  iteration: number;
  paused: boolean;
}

export interface InProgressItem {
  id: string;
  title?: string;
  agents: InProgressAgent[];
}

export function getInProgressItems(agents: AgentInfo[]): InProgressItem[] {
  const items = new Map<string, InProgressItem>();
  const agentKeys = new Set<string>();

  for (const agent of agents) {
    if (agent.status !== "running") continue;
    if (isHistoryAgent(agent)) continue;
    const id = agent.work_item_id?.trim();
    if (!id) continue;
    const title = agent.work_item_title?.trim() || undefined;
    const key = `${id}:${agent.agent_id}`;
    if (agentKeys.has(key)) continue;
    agentKeys.add(key);

    const entry = items.get(id) ?? { id, title, agents: [] };
    if (!entry.title && title) entry.title = title;
    entry.agents.push({
      name: agent.name,
      iteration: agent.iteration,
      paused: agent.paused === true,
    });
    items.set(id, entry);
  }

  return Array.from(items.values()).sort((a, b) => a.id.localeCompare(b.id));
}
