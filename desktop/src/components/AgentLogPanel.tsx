/**
 * Agent Log Panel - displays selected agent's logs in the main content area.
 *
 * Renders full log output with scrollback and collapsible tool/code blocks,
 * matching the main LogPanel's interactive UI.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentInfo } from "../types";
import {
  processLogsToRenderItems,
  stringsToLogEntries,
} from "../utils/logProcessor";
import { RenderLogItems } from "./LogComponents";

interface Props {
  agent: AgentInfo;
  onClose: () => void;
  showClose?: boolean;
}

const STATUS_INDICATOR: Record<string, { dot: string; label: string }> = {
  running: { dot: "agent-dot-running", label: "Running" },
  success: { dot: "agent-dot-success", label: "Done" },
  failed: { dot: "agent-dot-failed", label: "Failed" },
};

const ROBOT_AVATARS = [
  "🤖", "🦾", "⚙️", "🔩", "🛠️", "🧠", "💡", "🔬",
  "🚀", "🎯", "⚡", "🔮", "🌀", "🏗️", "🧩", "🎲",
];

function getAvatar(agentId: string): string {
  let hash = 0;
  for (let i = 0; i < agentId.length; i++) {
    hash = ((hash << 5) - hash + agentId.charCodeAt(i)) | 0;
  }
  return ROBOT_AVATARS[Math.abs(hash) % ROBOT_AVATARS.length];
}

function formatTimestamp(ts?: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
}

export function AgentLogPanel({ agent, onClose, showClose = true }: Props) {
  const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
  const logLines = agent.log_lines && agent.log_lines.length > 0
    ? agent.log_lines
    : agent.recent_logs;
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const threshold = 50;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    isUserScrolledUp.current = !atBottom;
  };

  // Capture the fallback timestamp once on mount (avoids Date.now() in render)
  const [fallbackTimestamp] = useState(() => Math.floor(Date.now() / 1000));

  // Convert string log lines to LogEntry format and process for rendering
  const renderItems = useMemo(() => {
    const baseTimestamp = agent.started_at ?? fallbackTimestamp;
    const logEntries = stringsToLogEntries(logLines, baseTimestamp);
    return processLogsToRenderItems(logEntries);
  }, [logLines, agent.started_at, fallbackTimestamp]);

  useEffect(() => {
    if (!isUserScrolledUp.current) {
      bottomRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [logLines]);

  return (
    <div className="agent-log-panel">
      <div className="agent-log-panel-header">
        {showClose && (
          <button className="agent-log-panel-close" onClick={onClose} title="Close agent logs">
            ✕
          </button>
        )}
        <span className="agent-log-panel-avatar">{getAvatar(agent.agent_id)}</span>
        <div className="agent-log-panel-info">
          <span className="agent-log-panel-name">{agent.name}</span>
          <span className="agent-log-panel-iter">v{agent.iteration}</span>
        </div>
        <div className="agent-log-panel-status">
          <span className={`agent-dot ${statusInfo.dot}`} title={statusInfo.label} />
          <span className={`agent-status-chip status-${agent.status}`}>{statusInfo.label}</span>
        </div>
        <div className="agent-log-panel-meta">
          <span className="agent-meta-item">
            <strong>ID:</strong> {agent.agent_id}
          </span>
          <span className="agent-meta-item">
            <strong>Last log:</strong> {formatTimestamp(agent.last_log_at ?? agent.last_updated)}
          </span>
        </div>
        <span className="log-count">{logLines.length} lines</span>
      </div>
      <div className="agent-log-panel-content log-entries" ref={containerRef} onScroll={handleScroll}>
        {logLines.length === 0 ? (
          <div className="agent-log-panel-empty">Waiting for output…</div>
        ) : (
          <RenderLogItems items={renderItems} />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
