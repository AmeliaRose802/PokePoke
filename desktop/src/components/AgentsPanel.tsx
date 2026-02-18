/**
 * Agents panel component.
 *
 * Displays running agents as cards on the right side of the UI.
 * Each card shows: agent name, iteration, robot avatar, and
 * a live preview of recent log lines.
 * Clicking a card selects it to display full logs in the main panel.
 */

import type { ReactElement } from "react";
import type { AgentInfo } from "../types";

interface Props {
  agents: AgentInfo[];
  selectedAgentId?: string | null;
  onSelectAgent?: (agentId: string | null) => void;
}

const ROBOT_AVATARS = [
  "🤖", "🦾", "⚙️", "🔩", "🛠️", "🧠", "💡", "🔬",
  "🚀", "🎯", "⚡", "🔮", "🌀", "🏗️", "🧩", "🎲",
];

/** Deterministic avatar based on agent_id hash */
function getAvatar(agentId: string): string {
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = ((hash << 5) - hash + agentId.charCodeAt(i)) | 0;
  }
  return ROBOT_AVATARS[Math.abs(hash) % ROBOT_AVATARS.length];
}

function getAgentPrimaryLabel(agent: AgentInfo): string {
  if (agent.work_item_id) {
    return agent.work_item_title
      ? `${agent.work_item_id}: ${agent.work_item_title}`
      : agent.work_item_id;
  }
  return agent.name;
}

const STATUS_INDICATOR: Record<string, { dot: string; label: string }> = {
  running: { dot: "agent-dot-running", label: "Running" },
  success: { dot: "agent-dot-success", label: "Done" },
  failed: { dot: "agent-dot-failed", label: "Failed" },
};

export function AgentsPanel({
  agents,
  selectedAgentId,
  onSelectAgent,
}: Props) {
  const agentIdSet = new Set(agents.map((a) => a.agent_id));
  const childrenByParent = new Map<string, AgentInfo[]>();
  const rootAgents: AgentInfo[] = [];

  for (const agent of agents) {
    const parentId = agent.parent_agent_id ?? null;
    if (parentId && agentIdSet.has(parentId)) {
      const siblings = childrenByParent.get(parentId) ?? [];
      siblings.push(agent);
      childrenByParent.set(parentId, siblings);
    } else {
      rootAgents.push(agent);
    }
  }

  const renderAgentCard = (agent: AgentInfo, depth: number) => {
    const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
    const isSelected = selectedAgentId === agent.agent_id;
    const depthClass = depth > 0 ? " agent-card-child" : "";
    const label = getAgentPrimaryLabel(agent);
    const roleLabel = agent.work_item_id ? agent.name : null;

    return (
      <div
        key={agent.agent_id}
        className={`agent-card agent-card-${agent.status}${isSelected ? " agent-card-selected" : ""}${depthClass}`}
        role={onSelectAgent ? "button" : undefined}
        tabIndex={onSelectAgent ? 0 : undefined}
        onClick={() => onSelectAgent?.(isSelected ? null : agent.agent_id)}
        onKeyDown={(evt) => {
          if (evt.key === "Enter" || evt.key === " ") {
            evt.preventDefault();
            onSelectAgent?.(isSelected ? null : agent.agent_id);
          }
        }}
      >
        <div className="agent-card-top">
          <span className="agent-card-avatar">{getAvatar(agent.agent_id)}</span>
          <div className="agent-card-info">
            <span className="agent-card-name">{label}</span>
            <span className="agent-card-iter">v{agent.iteration}</span>
            {roleLabel ? (
              <span className="agent-card-subtitle">{roleLabel}</span>
            ) : null}
          </div>
          <span className={`agent-dot ${statusInfo.dot}`} title={statusInfo.label} />
        </div>
        <div className="agent-card-logs">
          {agent.recent_logs.length === 0 ? (
            <span className="agent-card-no-logs">Waiting for output…</span>
          ) : (
            agent.recent_logs.map((line, i) => (
              <div key={i} className="agent-card-log-line">{line}</div>
            ))
          )}
        </div>
      </div>
    );
  };

  const renderAgentTree = (agent: AgentInfo, depth: number): ReactElement[] => {
    const nodes = [renderAgentCard(agent, depth)];
    const children = childrenByParent.get(agent.agent_id) ?? [];
    children.forEach((child) => {
      nodes.push(...renderAgentTree(child, depth + 1));
    });
    return nodes;
  };

  const renderedAgents = rootAgents.flatMap((agent) => renderAgentTree(agent, 0));

  if (agents.length === 0) {
    return (
      <aside className="agents-panel">
        <div className="agents-panel-header">
          <span>🤖 Agents</span>
          <span className="agents-count">0</span>
        </div>
        <div className="agents-empty">No agents running</div>
      </aside>
    );
  }

  return (
    <aside className="agents-panel">
      <div className="agents-panel-header">
        <span>🤖 Agents</span>
        <span className="agents-count">{agents.length}</span>
      </div>
      <div className="agents-scroll">
        {renderedAgents}
      </div>
    </aside>
  );
}
