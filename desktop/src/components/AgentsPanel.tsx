/**
 * Agents panel component.
 *
 * Displays running agents as cards on the right side of the UI.
 * Each card shows: agent name, iteration, robot avatar, and
 * a live preview of recent log lines.
 */

import { useEffect, useMemo, useRef } from "react";
import type { AgentInfo } from "../types";

interface Props {
  agents: AgentInfo[];
  selectedAgentId?: string | null;
  selectedAgentDetail?: AgentInfo | null;
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

const STATUS_INDICATOR: Record<string, { dot: string; label: string }> = {
  running: { dot: "agent-dot-running", label: "Running" },
  success: { dot: "agent-dot-success", label: "Done" },
  failed: { dot: "agent-dot-failed", label: "Failed" },
};

function formatTimestamp(ts?: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
}

function AgentDetailView({ agent, onBack }: { agent: AgentInfo; onBack: () => void }) {
  const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
  const logLines = useMemo(
    () => (agent.log_lines && agent.log_lines.length > 0 ? agent.log_lines : agent.recent_logs),
    [agent.log_lines, agent.recent_logs]
  );
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "auto" });
  }, [logLines]);

  return (
    <div className="agent-detail">
      <div className="agents-panel-header agent-detail-header">
        <button className="agent-back-btn" onClick={onBack}>
          ← Agents
        </button>
        <div className="agent-detail-title">
          <span className="agent-card-avatar">{getAvatar(agent.agent_id)}</span>
          <div className="agent-card-info">
            <span className="agent-card-name">{agent.name}</span>
            <span className="agent-card-iter">v{agent.iteration}</span>
          </div>
        </div>
        <div className="agent-detail-status">
          <span className={`agent-dot ${statusInfo.dot}`} title={statusInfo.label} />
          <span className={`agent-status-chip status-${agent.status}`}>{statusInfo.label}</span>
        </div>
      </div>
      <div className="agent-detail-meta">
        <span className="agent-meta-item">
          <strong>ID:</strong> {agent.agent_id}
        </span>
        <span className="agent-meta-item">
          <strong>Last log:</strong> {formatTimestamp(agent.last_log_at ?? agent.last_updated)}
        </span>
      </div>
      <div className="agent-detail-logs">
        {logLines.length === 0 ? (
          <div className="agent-detail-empty">Waiting for output…</div>
        ) : (
          logLines.map((line, i) => (
            <div key={`${agent.agent_id}-log-${i}`} className="agent-detail-log-line">
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

export function AgentsPanel({
  agents,
  selectedAgentId,
  selectedAgentDetail,
  onSelectAgent,
}: Props) {
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

  const detailAgent =
    selectedAgentId != null
      ? selectedAgentDetail ?? agents.find((agent) => agent.agent_id === selectedAgentId) ?? null
      : null;

  if (detailAgent) {
    return (
      <aside className="agents-panel">
        <AgentDetailView agent={detailAgent} onBack={() => onSelectAgent?.(null)} />
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
            <div
              key={agent.agent_id}
              className={`agent-card agent-card-${agent.status}`}
              role={onSelectAgent ? "button" : undefined}
              tabIndex={onSelectAgent ? 0 : undefined}
              onClick={() => onSelectAgent?.(agent.agent_id)}
              onKeyDown={(evt) => {
                if (evt.key === "Enter" || evt.key === " ") {
                  evt.preventDefault();
                  onSelectAgent?.(agent.agent_id);
                }
              }}
            >
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
