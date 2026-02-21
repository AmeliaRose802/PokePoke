/**
 * Agent Log Panel - displays selected agent's logs in the main content area.
 *
 * Renders full log output with scrollback and collapsible tool/code blocks,
 * matching the main LogPanel's interactive UI.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import type { AgentInfo } from "../types";
import { useBridge } from "../useBridge";
import {
  getAgentAvatar,
  getAgentPrimaryLabel,
  getAgentType,
  isGateAgent,
} from "../utils/agentHelpers";
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
  "🐍", "🦎", "🕷️", "🦇", "🦋", "🐛", "🐝", "🐞",
  "🌿", "🍃", "🌱", "🌳", "🌴", "🌲", "🎋", "🌾",
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
  const { getAgentDetail, agents } = useBridge();
  const [detailedAgent, setDetailedAgent] = useState<AgentInfo | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const isGate = isGateAgent(agent);
  const linkedParent =
    agent.parent_agent_id && isGate
      ? agents.find((candidate) => candidate.agent_id === agent.parent_agent_id) ?? null
      : null;
  const parentLabel = linkedParent
    ? getAgentPrimaryLabel(linkedParent)
    : agent.parent_agent_id ?? null;

  const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
  
  // Use detailed agent logs if available, otherwise fall back to basic agent info
  const agentToUse = detailedAgent || agent;
  const agentType = getAgentType(agentToUse);
  const agentIconPath = getAgentAvatar(agentToUse);
  const fallbackAvatar = getAvatar(agentToUse.agent_id);
  const iconAlt = `${agentType ?? "agent"} icon`;
  const logLines = agentToUse.log_lines && agentToUse.log_lines.length > 0
    ? agentToUse.log_lines
    : agentToUse.recent_logs;
  
  const primaryLabel = getAgentPrimaryLabel(agent);
  // Show the friendly name prominently when it differs from the primary label
  const friendlyName = agent.name !== primaryLabel ? agent.name : null;
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);

  // Fetch detailed agent information when agent changes
  useEffect(() => {
    async function fetchDetailedAgent() {
      setIsLoadingDetail(true);
      setDetailError(null);
      try {
        const detailed = await getAgentDetail(agent.agent_id);
        setDetailedAgent(detailed);
      } catch (error) {
        setDetailError(error instanceof Error ? error.message : 'Failed to load detailed logs');
        console.warn('Failed to fetch agent detail:', error);
      } finally {
        setIsLoadingDetail(false);
      }
    }
    
    fetchDetailedAgent();
  }, [agent.agent_id, getAgentDetail]);

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
        {agentIconPath ? (
          <img
            src={agentIconPath}
            alt={iconAlt}
            className="agent-log-panel-avatar agent-log-panel-icon"
            onError={(e) => {
              const parent = e.currentTarget.parentElement;
              if (parent) {
                parent.innerHTML = `<span class="agent-log-panel-avatar">${fallbackAvatar}</span>`;
              }
            }}
          />
        ) : (
          <span className="agent-log-panel-avatar">{fallbackAvatar}</span>
        )}
        <div className="agent-log-panel-info">
          <span className="agent-log-panel-name">{primaryLabel}</span>
          <span className="agent-log-panel-iter">v{agent.iteration}</span>
          {friendlyName ? (
            <span className="agent-log-panel-friendly-name">{friendlyName}</span>
          ) : null}
        </div>
        <div className="agent-log-panel-status">
          <span className={`agent-dot ${statusInfo.dot}`} title={statusInfo.label} />
          <span className={`agent-status-chip status-${agent.status}`}>{statusInfo.label}</span>
        </div>
        {isGate && parentLabel ? (
          <div className="agent-log-panel-link">
            <span className="agent-card-link-label">Gate for</span>
            <span className="agent-card-link-target" title={parentLabel}>
              {parentLabel}
            </span>
          </div>
        ) : null}
        <div className="agent-log-panel-meta">
          <span className="agent-meta-item">
            <strong>ID:</strong> {agent.agent_id}
          </span>
          {agent.work_item_id ? (
            <span className="agent-meta-item">
              <strong>Work item:</strong> {agent.work_item_id}
              {agent.work_item_title ? ` — ${agent.work_item_title}` : ""}
            </span>
          ) : null}
          <span className="agent-meta-item">
            <strong>Last log:</strong> {formatTimestamp(agent.last_log_at ?? agent.last_updated)}
          </span>
        </div>
        {agent.modified_files && agent.modified_files.length > 0 ? (
          <div className="agent-log-panel-files">
            <strong>Modified files:</strong>
            <ul className="agent-log-panel-file-list">
              {agent.modified_files.map((file, i) => (
                <li key={i}>{file}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <span className="log-count">
          {isLoadingDetail ? "Loading detailed logs..." : `${logLines.length} lines`}
          {detailError && " (Error loading details)"}
        </span>
      </div>
      <div className="agent-log-panel-content log-entries" ref={containerRef} onScroll={handleScroll}>
        {isLoadingDetail && logLines.length === 0 ? (
          <div className="agent-log-panel-empty">Loading detailed logs…</div>
        ) : logLines.length === 0 ? (
          <div className="agent-log-panel-empty">Waiting for output…</div>
        ) : (
          <RenderLogItems items={renderItems} />
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
