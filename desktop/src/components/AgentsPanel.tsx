/**
 * Agents panel component.
 *
 * Displays running agents as cards on the right side of the UI.
 * Each card shows: agent name, iteration, robot avatar, and
 * a live preview of recent log lines.
 */

import type { AgentInfo } from "../types";

interface Props {
  agents: AgentInfo[];
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

const STATUS_INDICATOR: Record<string, { dot: string; label: string }> = {
  running: { dot: "agent-dot-running", label: "Running" },
  success: { dot: "agent-dot-success", label: "Done" },
  failed: { dot: "agent-dot-failed", label: "Failed" },
};

export function AgentsPanel({ agents }: Props) {
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
        {agents.map((agent) => {
          const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
          return (
            <div key={agent.agent_id} className={`agent-card agent-card-${agent.status}`}>
              <div className="agent-card-top">
                <span className="agent-card-avatar">{getAvatar(agent.agent_id)}</span>
                <div className="agent-card-info">
                  <span className="agent-card-name">{agent.name}</span>
                  <span className="agent-card-iter">v{agent.iteration}</span>
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
        })}
      </div>
    </aside>
  );
}
