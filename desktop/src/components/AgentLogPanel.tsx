/**
 * Agent Log Panel - displays selected agent's logs in the main content area.
 *
 * Renders full log output with scrollback and collapsible tool/code blocks,
 * matching the main LogPanel's interactive UI.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { AgentInfo } from "../types";
import { useBridge } from "../useBridge";
import {
  formatModelName,
  getAgentAvatar,
  getAgentPrimaryLabel,
  getAgentType,
  isGateAgent,
} from "../utils/agentHelpers";
import { getEmojiAvatar, STATUS_INDICATOR } from "../utils/agentsPanelHelpers";
import { groupPlainLines, processLogsToRenderItems, stringsToLogEntries } from "../utils/logProcessor";
import { RenderLogItems } from "./LogComponents";

interface Props {
  agent: AgentInfo;
  onClose: () => void;
  showClose?: boolean;
}

function formatTimestamp(ts?: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });
}

function formatElapsedTime(startTs?: number | null): string {
  if (!startTs) return "—";
  const elapsedSeconds = Math.floor(Date.now() / 1000) - startTs;
  if (elapsedSeconds < 60) return `${elapsedSeconds}s`;
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

export function AgentLogPanel({ agent, onClose, showClose = true }: Props) {
  const { getAgentDetail, agents } = useBridge();
  const [detailedAgent, setDetailedAgent] = useState<AgentInfo | null>(null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const isGate = isGateAgent(agent);
  const linkedParent = isGate
    ? (agents.find((candidate) => {
        if (agent.parent_card_id) {
          return (candidate.card_id ?? candidate.agent_id) === agent.parent_card_id;
        }
        return candidate.agent_id === agent.parent_agent_id;
      }) ?? null)
    : null;
  const parentLabel = linkedParent ? getAgentPrimaryLabel(linkedParent) : (agent.parent_agent_id ?? null);

  const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;

  // Prioritize live agent data for logs, but use detailed agent for metadata if available
  const agentToUse = detailedAgent || agent;
  const agentType = getAgentType(agentToUse);
  const agentIconPath = getAgentAvatar(agentToUse);
  const fallbackAvatar = getEmojiAvatar(agentToUse.base_agent_id ?? agentToUse.agent_id);
  const iconAlt = `${agentType ?? "agent"} icon`;
  const [iconFailed, setIconFailed] = useState(false);
  const agentPrompt = agentToUse.agent_prompt;
  const hasPrompt = Boolean(agentPrompt && agentPrompt.trim().length > 0);
  const promptLineCount = hasPrompt ? agentPrompt!.split(/\r?\n/).length : 0;

  const promptRef = useRef<HTMLDetailsElement>(null);

  // Memoize logLines to prevent dependency changes on every render
  const logLines = useMemo(() => {
    // Priority: 1) Live agent recent_logs, 2) Detailed agent log_lines, 3) Fallback to empty
    if (agent.recent_logs && agent.recent_logs.length > 0) {
      return agent.recent_logs;
    }
    if (detailedAgent?.log_lines && detailedAgent.log_lines.length > 0) {
      return detailedAgent.log_lines;
    }
    return [];
  }, [agent.recent_logs, detailedAgent?.log_lines]);

  const primaryLabel = getAgentPrimaryLabel(agent);
  // Show the friendly name prominently when it differs from the primary label
  const friendlyName = agent.name !== primaryLabel ? agent.name : null;
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);
  const isProgrammaticScroll = useRef(false);

  // Fetch detailed agent information when agent changes
  useEffect(() => {
    async function fetchDetailedAgent() {
      setIsLoadingDetail(true);
      setDetailError(null);
      try {
        const detailKey = agent.card_id ?? agent.agent_id;
        const detailed = await getAgentDetail(detailKey);
        setDetailedAgent(detailed);
      } catch (error) {
        setDetailError(error instanceof Error ? error.message : "Failed to load detailed logs");
        console.warn("Failed to fetch agent detail:", error);
      } finally {
        setIsLoadingDetail(false);
      }
    }

    fetchDetailedAgent();
  }, [agent.card_id, agent.agent_id, getAgentDetail]);

  // Re-poll detailed agent data periodically for running agents to keep logs fresh
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const shouldRepoll = agent.status === "running" && !agent.paused;
    if (shouldRepoll) {
      intervalId = setInterval(async () => {
        try {
          const detailKey = agent.card_id ?? agent.agent_id;
          const detailed = await getAgentDetail(detailKey);
          setDetailedAgent(detailed);
        } catch (error) {
          console.warn("Failed to refresh agent detail:", error);
          // Don't update error state for background refreshes
        }
      }, 5000); // Re-poll every 5 seconds for running agents
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [agent.status, agent.paused, agent.card_id, agent.agent_id, getAgentDetail]);

  const handleScroll = () => {
    if (isProgrammaticScroll.current) return;
    const el = containerRef.current;
    if (!el) return;
    const threshold = 50;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    isUserScrolledUp.current = !atBottom;
  };

  // Capture the fallback timestamp once on mount (avoids Date.now() in render)
  const [fallbackTimestamp] = useState(() => Math.floor(Date.now() / 1000));

  // Convert string log lines to LogEntry format and process for rendering.
  // groupPlainLines merges consecutive non-structured lines so that they
  // render as a single block instead of individual bubbles.
  const renderItems = useMemo(() => {
    const baseTimestamp = agent.started_at ?? fallbackTimestamp;
    const grouped = groupPlainLines(logLines);
    const logEntries = stringsToLogEntries(grouped, baseTimestamp);
    return processLogsToRenderItems(logEntries);
  }, [logLines, agent.started_at, fallbackTimestamp]);

  // Auto-scroll to bottom when new logs arrive, unless user has scrolled up.
  // useLayoutEffect prevents visible flicker between render and scroll adjustment.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el || isUserScrolledUp.current) return;
    isProgrammaticScroll.current = true;
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(() => {
      isProgrammaticScroll.current = false;
    });
  }, [logLines]);

  return (
    <div className="agent-log-panel">
      <div className="agent-log-panel-header">
        {showClose && (
          <button className="agent-log-panel-close" onClick={onClose} title="Close agent logs">
            ✕
          </button>
        )}
        {agentIconPath && !iconFailed ? (
          <img
            src={agentIconPath}
            alt={iconAlt}
            className="agent-log-panel-avatar agent-log-panel-icon agent-log-panel-snake-icon"
            onError={() => setIconFailed(true)}
          />
        ) : (
          <span className="agent-log-panel-avatar">{fallbackAvatar}</span>
        )}
        <div className="agent-log-panel-info">
          <span className="agent-log-panel-name">{primaryLabel}</span>
          <span className="agent-log-panel-iter">v{agent.iteration}</span>
          {friendlyName ? <span className="agent-log-panel-friendly-name">{friendlyName}</span> : null}
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
            <strong>ID:</strong> {agent.base_agent_id ?? agent.agent_id}
          </span>
          <span className="agent-meta-item">
            <strong>Started:</strong> {formatTimestamp(agent.started_at)} ({formatElapsedTime(agent.started_at)})
          </span>
          <span className="agent-meta-item">
            <strong>Model:</strong> {formatModelName(agent.model)}
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
              {agent.modified_files.map((file) => (
                <li key={file}>{file}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {hasPrompt ? (
          <details className="log-accordion agent-log-panel-prompt" ref={promptRef}>
            <summary className="log-accordion-summary">
              <span className="log-accordion-chevron">▸</span>
              <span className="log-message">Agent Prompt{promptLineCount ? ` — ${promptLineCount} lines` : ""}</span>
            </summary>
            <div className="log-accordion-details">
              <button
                className="agent-log-panel-prompt-close"
                onClick={() => {
                  if (promptRef.current) promptRef.current.open = false;
                }}
                title="Collapse prompt"
              >
                ✕ Close
              </button>
              <pre className="agent-log-panel-prompt-content">{agentPrompt}</pre>
            </div>
          </details>
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
          <div className="agent-log-panel-logs">
            <RenderLogItems items={renderItems} />
          </div>
        )}
      </div>
    </div>
  );
}
