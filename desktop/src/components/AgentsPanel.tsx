/**
 * Agents panel component.
 *
 * Displays running agents as cards on the right side of the UI.
 * Each card shows: agent name, iteration, robot avatar, and
 * a live preview of recent log lines.
 * Clicking a card selects it to display full logs in the main panel.
 *
 * Agents are grouped by session. Previous sessions are collapsed
 * by default and can be expanded by clicking the session header.
 */

import { type ReactElement,useState } from "react";

import type { AgentInfo } from "../types";
import {
  getAgentAvatar,
  getAgentPrimaryLabel,
  getAgentType,
  isGateAgent,
} from "../utils/agentHelpers";

interface Props {
  agents: AgentInfo[];
  currentSessionId?: string | null;
  selectedAgentId?: string | null;
  onSelectAgent?: (agentId: string | null) => void;
  onPauseAgent?: (agentId: string) => void;
  onResumeAgent?: (agentId: string) => void;
  onSpawnAgent?: () => void;
  orchestratorRunning?: boolean;
  spawnAtLimit?: boolean;
}

const ROBOT_AVATARS = [
  "🐍", "🦎", "🕷️", "🦇", "🦋", "🐛", "🐝", "🐞",
  "🤖", "🔧", "⚡", "🎯", "🔮", "🎲", "🔬", "🧩",
];

/** Deterministic avatar based on agent_id hash (fallback for agents without work items) */
function getEmojiAvatar(agentId: string): string {
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

const GATE_STATUS_COPY: Record<AgentInfo["status"], string> = {
  running: "Gate running",
  success: "Gate passed",
  failed: "Gate failed",
};

const UNKNOWN_SESSION = "__unknown__";

/** Format a session_id (epoch timestamp string) as a readable label. */
function formatSessionLabel(sessionId: string): string {
  if (sessionId === UNKNOWN_SESSION) return "Previous Session";
  const epoch = parseFloat(sessionId);
  if (isNaN(epoch)) return `Session ${sessionId}`;
  const date = new Date(epoch * 1000);
  const ymd = date.toLocaleDateString(undefined, { year: "numeric", month: "2-digit", day: "2-digit" });
  const hm = date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  return `Session ${ymd} ${hm}`;
}

/** Group agents by session_id, preserving order (most recent last). */
function groupBySession(
  agents: AgentInfo[]
): { sessionId: string; agents: AgentInfo[] }[] {
  const map = new Map<string, AgentInfo[]>();
  for (const agent of agents) {
    const sid = agent.session_id ?? UNKNOWN_SESSION;
    const group = map.get(sid);
    if (group) {
      group.push(agent);
    } else {
      map.set(sid, [agent]);
    }
  }
  return Array.from(map.entries()).map(([sessionId, sessionAgents]) => ({
    sessionId,
    agents: sessionAgents,
  }));
}

export function AgentsPanel({
  agents,
  currentSessionId,
  selectedAgentId,
  onSelectAgent,
  onPauseAgent,
  onResumeAgent,
  onSpawnAgent,
  orchestratorRunning = false,
  spawnAtLimit = false,
}: Props) {
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(
    new Set()
  );
  const [expandedCompletedSections, setExpandedCompletedSections] = useState<Set<string>>(
    new Set()
  );

  const toggleSession = (sessionId: string) => {
    setExpandedSessions((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };

  const toggleCompletedSection = (sessionId: string) => {
    setExpandedCompletedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sessionId)) {
        next.delete(sessionId);
      } else {
        next.add(sessionId);
      }
      return next;
    });
  };


  const agentIdSet = new Set(agents.map((a) => a.agent_id));
  const childrenByParent = new Map<string, AgentInfo[]>();

  for (const agent of agents) {
    const parentId = agent.parent_agent_id ?? null;
    if (parentId && agentIdSet.has(parentId)) {
      const siblings = childrenByParent.get(parentId) ?? [];
      siblings.push(agent);
      childrenByParent.set(parentId, siblings);
    }
  }

  const renderAgentCard = (
    agent: AgentInfo,
    depth: number,
    parent?: AgentInfo
  ) => {
    const statusInfo =
      STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
    const isSelected = selectedAgentId === agent.agent_id;
    const isPaused = agent.paused === true;
    const depthClass = depth > 0 ? " agent-card-child" : "";
    const isGate = isGateAgent(agent);
    const gateClass = isGate ? " agent-card-gate" : "";
    const pausedClass = isPaused ? " agent-card-paused" : "";
    const parentLabel = parent ? getAgentPrimaryLabel(parent) : null;
    const baseLabel = getAgentPrimaryLabel(agent);
    const label = isGate && parentLabel ? parentLabel : baseLabel;
    const roleLabel = agent.work_item_id ? agent.name : null;
    const gateChildForParent =
      !isGate
        ? (childrenByParent.get(agent.agent_id) ?? []).find(isGateAgent) ?? null
        : null;
    const gateSummary = gateChildForParent
      ? GATE_STATUS_COPY[gateChildForParent.status] ??
        GATE_STATUS_COPY.running
      : null;
    const gateTargetSummary =
      isGate && parent
        ? `${parent.name}${parent.iteration ? ` · v${parent.iteration}` : ""}`
        : agent.parent_agent_id ?? null;
    const agentType = getAgentType(agent);
    const agentIconPath = getAgentAvatar(agent);
    const fallbackEmoji = getEmojiAvatar(agent.agent_id);
    const iconAlt = `${agentType ?? "agent"} icon`;

    return (
      <div
        key={agent.agent_id}
        className={`agent-card agent-card-${agent.status}${
          isSelected ? " agent-card-selected" : ""
        }${depthClass}${gateClass}${pausedClass}`}
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
          {(() => {
            if (agentIconPath) {
              return (
                <img 
                  src={agentIconPath} 
                  alt={iconAlt}
                  className="agent-card-avatar agent-card-snake-icon agent-card-icon"
                  onError={(e) => {
                    // Fallback to emoji if image fails to load
                    const target = e.currentTarget;
                    const parent = target.parentElement;
                    if (parent) {
                      parent.innerHTML = `<span class="agent-card-avatar">${fallbackEmoji}</span>`;
                    }
                  }}
                />
              );
            } else {
              return <span className="agent-card-avatar">{fallbackEmoji}</span>;
            }
          })()}
          <div className="agent-card-info">
            <span className="agent-card-name">{label}</span>
            <span className="agent-card-iter">v{agent.iteration}</span>
            {roleLabel ? (
              <span className="agent-card-subtitle">{roleLabel}</span>
            ) : null}
            {isGate && gateTargetSummary ? (
              <span className="agent-card-link-label gate-card-target">
                {gateTargetSummary}
              </span>
            ) : null}
          </div>
          <div className="agent-card-status">
            {gateSummary && gateChildForParent ? (
              <span
                className={`agent-gate-chip gate-${gateChildForParent.status}`}
                title={gateSummary}
              >
                {gateSummary}
              </span>
            ) : null}
            <span
              className={`agent-dot ${statusInfo.dot}`}
              title={statusInfo.label}
            />
          </div>
          {isPaused && <span className="agent-paused-badge" title="Paused">⏸</span>}
          {agent.status === "running" && (
            <button
              className={`agent-pause-btn${isPaused ? " paused" : ""}`}
              title={isPaused ? "Resume agent" : "Pause agent"}
              onClick={(evt) => {
                evt.stopPropagation();
                if (isPaused) {
                  onResumeAgent?.(agent.agent_id);
                } else {
                  onPauseAgent?.(agent.agent_id);
                }
              }}
            >
              {isPaused ? "▶" : "⏸"}
            </button>
          )}
        </div>

        {agent.modified_files && agent.modified_files.length > 0 ? (
          <div className="agent-card-files">
            <span className="agent-card-files-label">
              📁 {agent.modified_files.length} file{agent.modified_files.length !== 1 ? "s" : ""}
            </span>
            <span className="agent-card-files-list" title={agent.modified_files.join("\n")}>
              {agent.modified_files.slice(0, 3).join(", ")}
              {agent.modified_files.length > 3 ? ` +${agent.modified_files.length - 3} more` : ""}
            </span>
          </div>
        ) : null}
        <div className="agent-card-logs">
          {agent.recent_logs.length === 0 ? (
            <span className="agent-card-no-logs">{isPaused ? "Paused" : "Waiting for output…"}</span>
          ) : (
            agent.recent_logs.map((line, i) => (
              <div key={i} className="agent-card-log-line">{line}</div>
            ))
          )}
        </div>
      </div>
    );
  };

  // Group agents by session
  const sessionGroups = groupBySession(agents);
  const hasMultipleSessions = sessionGroups.length > 1;

  const renderSessionGroup = (
    group: { sessionId: string; agents: AgentInfo[] },
    isCurrent: boolean
  ) => {
    const isExpanded =
      isCurrent || expandedSessions.has(group.sessionId);

    // Build trees for this session's agents
    const sessionAgentIdSet = new Set(group.agents.map((a) => a.agent_id));
    const sessionChildrenByParent = new Map<string, AgentInfo[]>();
    const sessionRootAgents: AgentInfo[] = [];
    for (const agent of group.agents) {
      const parentId = agent.parent_agent_id ?? null;
      if (parentId && sessionAgentIdSet.has(parentId)) {
        const siblings = sessionChildrenByParent.get(parentId) ?? [];
        siblings.push(agent);
        sessionChildrenByParent.set(parentId, siblings);
      } else {
        sessionRootAgents.push(agent);
      }
    }

    const renderSessionAgentTree = (
      agent: AgentInfo,
      depth: number,
      parent?: AgentInfo
    ): ReactElement[] => {
      const nodes = [renderAgentCard(agent, depth, parent)];
      const children = sessionChildrenByParent.get(agent.agent_id) ?? [];
      children.forEach((child) => {
        nodes.push(...renderSessionAgentTree(child, depth + 1, agent));
      });
      return nodes;
    };

    const treeHasRunning = (agent: AgentInfo): boolean => {
      if (agent.status === "running") return true;
      const children = sessionChildrenByParent.get(agent.agent_id) ?? [];
      return children.some(treeHasRunning);
    };

    const treeHasFailure = (agent: AgentInfo): boolean => {
      if (agent.status === "failed") return true;
      const children = sessionChildrenByParent.get(agent.agent_id) ?? [];
      return children.some(treeHasFailure);
    };

    const activeRootAgents = sessionRootAgents.filter(treeHasRunning);
    const completedRootAgents = sessionRootAgents.filter(
      (agent) => !treeHasRunning(agent)
    );

    const renderedActiveAgents = activeRootAgents.flatMap((agent) =>
      renderSessionAgentTree(agent, 0)
    );
    const renderedCompletedAgents = completedRootAgents.flatMap((agent) =>
      renderSessionAgentTree(agent, 0)
    );

    const completedFailedCount = completedRootAgents.filter(treeHasFailure).length;
    const completedSuccessCount = completedRootAgents.length - completedFailedCount;

    const isCompletedExpanded = expandedCompletedSections.has(group.sessionId);

    const renderedSections = (
      <div className="agent-sections">
        <div className="agent-section agent-section-active">
          <div className="agent-section-title">
            <span className="agent-section-label">Active</span>
            <span className="agent-section-count">{activeRootAgents.length}</span>
          </div>
          {renderedActiveAgents.length > 0 ? (
            <div className="agent-section-content">{renderedActiveAgents}</div>
          ) : (
            <div className="agent-section-empty">No active agents</div>
          )}
        </div>

        {completedRootAgents.length > 0 ? (
          <div className="agent-section agent-section-completed">
            <button
              className="agent-section-header"
              onClick={() => toggleCompletedSection(group.sessionId)}
              aria-expanded={isCompletedExpanded}
              type="button"
            >
              <span className="agent-section-chevron">
                {isCompletedExpanded ? "▾" : "▸"}
              </span>
              <span className="agent-section-label">Completed</span>
              <span className="agent-section-count">{completedRootAgents.length}</span>
              <span className="agent-section-summary">
                {completedFailedCount > 0
                  ? `${completedSuccessCount} ok · ${completedFailedCount} failed`
                  : `${completedSuccessCount} ok`}
              </span>
            </button>
            {isCompletedExpanded && (
              <div className="agent-section-content">{renderedCompletedAgents}</div>
            )}
          </div>
        ) : null}
      </div>
    );

    if (!hasMultipleSessions) {
      return <div key={group.sessionId}>{renderedSections}</div>;
    }

    const label = isCurrent
      ? "Current session"
      : formatSessionLabel(group.sessionId);

    return (
      <div key={group.sessionId} className="session-group">
        <button
          className={`session-group-header${isCurrent ? " session-group-current" : ""}`}
          onClick={() => !isCurrent && toggleSession(group.sessionId)}
          aria-expanded={isExpanded}
        >
          <span className="session-group-chevron">
            {isExpanded ? "▾" : "▸"}
          </span>
          <span className="session-group-label">{label}</span>
          <span className="session-group-count">{group.agents.length}</span>
        </button>
        {isExpanded && (
          <div className="session-group-content">{renderedSections}</div>
        )}
      </div>
    );
  };

  if (agents.length === 0) {
    return (
      <aside className="agents-panel">
        <div className="agents-panel-header">
          <span>🐍 Agents</span>
          <span className="agents-count">0</span>
          {orchestratorRunning && onSpawnAgent && (
            <button
              className="agents-spawn-btn"
              onClick={onSpawnAgent}
              title="Spawn additional agent"
              disabled={spawnAtLimit}
            >
              +
            </button>
          )}
        </div>
        <div className="agents-empty">No agents running</div>
      </aside>
    );
  }

  return (
    <aside className="agents-panel">
      <div className="agents-panel-header">
        <span>🐍 Agents</span>
        <span className="agents-count">{agents.length}</span>
        {orchestratorRunning && onSpawnAgent && (
          <button
            className="agents-spawn-btn"
            onClick={onSpawnAgent}
            title={spawnAtLimit ? "At max agent limit — increase max_parallel_agents in Settings" : "Spawn additional agent"}
            disabled={spawnAtLimit}
          >
            +
          </button>
        )}
      </div>
      <div className="agents-scroll">
        {sessionGroups.map((group) =>
          renderSessionGroup(
            group,
            group.sessionId === currentSessionId ||
              (currentSessionId == null &&
                group === sessionGroups[sessionGroups.length - 1])
          )
        )}
      </div>
    </aside>
  );
}
