/** Agents panel: displays running/completed agent cards grouped by session. */

import { type Dispatch, type ReactElement, type SetStateAction, useState } from "react";

import type { AgentInfo } from "../types";
import {
  getAgentAvatar,
  getAgentPrimaryLabel,
  getAgentType,
  getCleanupDisplayLabel,
  isCleanupAgent,
  isGateAgent,
  parseGateVerdict,
} from "../utils/agentHelpers";
import {
  cardIdForAgent,
  countTreeNodes,
  formatSessionLabel,
  GATE_STATUS_COPY,
  getEmojiAvatar,
  groupBySession,
  groupByWorkItem,
  isHistoryAgent,
  parentKeysForAgent,
  resolveGateForDisplay,
  shouldShowAttemptLabel,
  STATUS_INDICATOR,
  UNGROUPED_WORK_ITEM,
} from "../utils/agentsPanelHelpers";
import { GateVerdictPreview } from "./GateVerdictPreview";
import { WorkItemGroupSection } from "./WorkItemGroupSection";

/** Image with React-safe fallback (no direct DOM mutation). */
function AgentIcon({ src, alt, className, fallback }: {
  src: string | null | undefined;
  alt: string;
  className: string;
  fallback: ReactElement;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return fallback;
  return <img src={src} alt={alt} className={className} onError={() => setFailed(true)} />;
}

interface Props {
  agents: AgentInfo[];
  currentSessionId?: string | null;
  selectedCardId?: string | null;
  onSelectAgent?: (agentId: string | null) => void;
  onPauseAgent?: (agentId: string) => void;
  onResumeAgent?: (agentId: string) => void;
  onSpawnAgent?: () => void;
  orchestratorRunning?: boolean;
  spawnAtLimit?: boolean;
}

export function AgentsPanel({
  agents,
  currentSessionId,
  selectedCardId,
  onSelectAgent,
  onPauseAgent,
  onResumeAgent,
  onSpawnAgent,
  orchestratorRunning = false,
  spawnAtLimit = false,
}: Props) {
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());
  const [expandedCompletedSections, setExpandedCompletedSections] = useState<Set<string>>(new Set());
  const [collapsedActiveSections, setCollapsedActiveSections] = useState<Set<string>>(new Set());
  const [collapsedWorkItems, setCollapsedWorkItems] = useState<Set<string>>(new Set());

  const toggleInSet = (setter: Dispatch<SetStateAction<Set<string>>>, key: string) => {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const renderAgentCard = (
    agent: AgentInfo,
    depth: number,
    parent: AgentInfo | undefined,
    sessionChildrenMap: Map<string, AgentInfo[]>,
  ) => {
    const statusInfo = STATUS_INDICATOR[agent.status] ?? STATUS_INDICATOR.running;
    const cardId = cardIdForAgent(agent);
    const isSelected = selectedCardId === cardId;
    const isHistory = isHistoryAgent(agent);
    const isPaused = agent.paused === true;
    const depthClass = depth > 0 ? " agent-card-child" : "";
    const isGate = isGateAgent(agent);
    const gateClass = isGate ? " agent-card-gate" : "";
    const pausedClass = isPaused ? " agent-card-paused" : "";
    const historyClass = isHistory ? " agent-card-history" : "";
    const parentLabel = parent ? getAgentPrimaryLabel(parent) : null;
    const baseLabel = getAgentPrimaryLabel(agent);
    const label = isGate && parentLabel ? parentLabel : baseLabel;
    const roleLabel = agent.work_item_id ? agent.name : null;
    const { gate: gateForDisplay, isRetryCycleRoot } = resolveGateForDisplay(agent, sessionChildrenMap);
    const gateSummary = gateForDisplay ? (GATE_STATUS_COPY[gateForDisplay.status] ?? GATE_STATUS_COPY.running) : null;
    const showAttempt = shouldShowAttemptLabel(agent, sessionChildrenMap);
    const gateTargetSummary =
      isGate && parent
        ? `${parent.name}${parent.iteration ? ` · Attempt ${parent.iteration}` : ""}`
        : (agent.parent_agent_id ?? null);
    const agentType = getAgentType(agent);
    const agentIconPath = getAgentAvatar(agent);
    const fallbackEmoji = getEmojiAvatar(agent.agent_id);
    const iconAlt = `${agentType ?? "agent"} icon`;

    return (
      <div
        key={agent.card_id ?? agent.agent_id}
        className={`agent-card agent-card-${agent.status}${
          isSelected ? " agent-card-selected" : ""
        }${depthClass}${gateClass}${pausedClass}${historyClass}`}
        role={onSelectAgent ? "button" : undefined}
        tabIndex={onSelectAgent ? 0 : undefined}
        onClick={() => onSelectAgent?.(cardId)}
        onKeyDown={(evt) => {
          if (evt.key === "Enter" || evt.key === " ") {
            evt.preventDefault();
            onSelectAgent?.(cardId);
          }
        }}
      >
        <div className="agent-card-top">
          <AgentIcon
              src={agentIconPath}
              alt={iconAlt}
              className="agent-card-avatar agent-card-snake-icon agent-card-icon"
              fallback={<span className="agent-card-avatar">{fallbackEmoji}</span>}
          />
          <div className="agent-card-info">
            <span className="agent-card-name">{label}</span>
            {showAttempt ? (
              <span className="agent-card-iter agent-attempt-label">Attempt {agent.iteration}</span>
            ) : (
              <span className="agent-card-iter">v{agent.iteration}</span>
            )}
            {roleLabel ? <span className="agent-card-subtitle">{roleLabel}</span> : null}
            {isGate && gateTargetSummary ? (
              <span className="agent-card-link-label gate-card-target">{gateTargetSummary}</span>
            ) : null}
          </div>
          <div className="agent-card-status">
            {gateSummary && gateForDisplay ? (
              <span
                className={`agent-gate-chip gate-${gateForDisplay.status}${isRetryCycleRoot ? " gate-final-outcome" : ""}`}
                title={isRetryCycleRoot ? `Final: ${gateSummary}` : gateSummary}
              >
                {isRetryCycleRoot ? `Final: ${gateSummary}` : gateSummary}
              </span>
            ) : null}
            <span className={`agent-dot ${statusInfo.dot}`} title={statusInfo.label} />
          </div>
          {isPaused && (
            <span className="agent-paused-badge" title="Paused">
              ⏸
            </span>
          )}
          {agent.status === "running" && !isHistory && (
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
          {isGate ? (
            (() => {
              const verdict = parseGateVerdict(agent.log_lines ?? agent.recent_logs);
              if (verdict) return <GateVerdictPreview verdict={verdict} />;
              return agent.recent_logs.length === 0 ? (
                <span className="agent-card-no-logs">Running gate check…</span>
              ) : (
                agent.recent_logs.map((line, i) => (
                  <div key={i} className="agent-card-log-line">
                    {line}
                  </div>
                ))
              );
            })()
          ) : agent.recent_logs.length === 0 ? (
            <span className="agent-card-no-logs">{isPaused ? "Paused" : "Waiting for output…"}</span>
          ) : (
            agent.recent_logs.map((line, i) => (
              <div key={i} className="agent-card-log-line">
                {line}
              </div>
            ))
          )}
        </div>
      </div>
    );
  };

  // Group agents by session
  const sessionGroups = groupBySession(agents);
  const hasMultipleSessions = sessionGroups.length > 1;

  const renderSessionGroup = (group: { sessionId: string; agents: AgentInfo[] }, isCurrent: boolean) => {
    const isExpanded = isCurrent || expandedSessions.has(group.sessionId);

    // Build trees for this session's agents
    const sessionAgentIdSet = new Set<string>();
    group.agents.forEach((agent) => {
      sessionAgentIdSet.add(cardIdForAgent(agent));
      sessionAgentIdSet.add(agent.agent_id);
    });
    const sessionChildrenByParent = new Map<string, AgentInfo[]>();
    const sessionRootAgents: AgentInfo[] = [];
    for (const agent of group.agents) {
      const parentId = parentKeysForAgent(agent).find((key) => sessionAgentIdSet.has(key)) ?? null;
      if (parentId) {
        const siblings = sessionChildrenByParent.get(parentId) ?? [];
        siblings.push(agent);
        sessionChildrenByParent.set(parentId, siblings);
      } else {
        sessionRootAgents.push(agent);
      }
    }

    const renderSessionAgentTree = (agent: AgentInfo, depth: number, parent?: AgentInfo): ReactElement[] => {
      const nodes = [renderAgentCard(agent, depth, parent, sessionChildrenByParent)];
      const allChildren = [
        ...(sessionChildrenByParent.get(cardIdForAgent(agent)) ?? sessionChildrenByParent.get(agent.agent_id) ?? []),
      ];

      // Separate retry children (linked via parent_card_id, non-gate) from other children
      const retryKids = allChildren.filter((c) => !isGateAgent(c) && !isCleanupAgent(c) && !!c.parent_card_id);
      const cleanupKids = allChildren.filter((c) => !isGateAgent(c) && isCleanupAgent(c) && !!c.parent_card_id);
      const otherKids = allChildren.filter((c) => isGateAgent(c) || !c.parent_card_id);

      // Render non-retry children (gates, maintenance sub-agents) newest-first
      otherKids
        .sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0))
        .forEach((child) => {
          nodes.push(...renderSessionAgentTree(child, depth + 1, agent));
        });

      // Render cleanup children with their own separator (distinct workflow phase)
      cleanupKids
        .sort((a, b) => (a.started_at ?? a.iteration) - (b.started_at ?? b.iteration))
        .forEach((child) => {
          nodes.push(
            <div
              key={`cleanup-sep-${child.card_id ?? child.agent_id}`}
              className={`agent-cleanup-separator${depth > 0 ? " agent-cleanup-separator-nested" : ""}`}
            >
              <span className="agent-cleanup-icon">🧹</span>
              <span className="agent-cleanup-label">{getCleanupDisplayLabel(child)}</span>
            </div>,
          );
          nodes.push(...renderSessionAgentTree(child, depth + 1, agent));
        });

      // Render retry children chronologically (oldest first) with separators
      retryKids
        .sort((a, b) => (a.started_at ?? a.iteration) - (b.started_at ?? b.iteration))
        .forEach((child) => {
          nodes.push(
            <div
              key={`retry-sep-${child.card_id ?? child.agent_id}`}
              className={`agent-retry-separator${depth > 0 ? " agent-retry-separator-nested" : ""}`}
            >
              <span className="agent-retry-arrow">↻</span>
              <span className="agent-retry-label">Retried with feedback</span>
            </div>,
          );
          nodes.push(...renderSessionAgentTree(child, depth + 1, agent));
        });
      return nodes;
    };

    const nodeHasRunningStatus = (candidate: AgentInfo): boolean =>
      candidate.status === "running" && !isHistoryAgent(candidate);

    const treeHasRunning = (agent: AgentInfo): boolean => {
      if (nodeHasRunningStatus(agent)) return true;
      const children =
        sessionChildrenByParent.get(cardIdForAgent(agent)) ?? sessionChildrenByParent.get(agent.agent_id) ?? [];
      return children.some(treeHasRunning);
    };

    const treeHasFailure = (agent: AgentInfo): boolean => {
      if (agent.status === "failed") return true;
      const children =
        sessionChildrenByParent.get(cardIdForAgent(agent)) ?? sessionChildrenByParent.get(agent.agent_id) ?? [];
      return children.some(treeHasFailure);
    };

    const activeRootAgents = sessionRootAgents.filter((agent) => isHistoryAgent(agent) || treeHasRunning(agent));
    const completedRootAgents = sessionRootAgents.filter((agent) => !isHistoryAgent(agent) && !treeHasRunning(agent));

    const renderGroupedAgentSection = (rootAgents: AgentInfo[]): ReactElement[] => {
      const workItemGroups = groupByWorkItem(rootAgents);
      const elements: ReactElement[] = [];

      for (const wiGroup of workItemGroups) {
        if (wiGroup.workItemId === UNGROUPED_WORK_ITEM || wiGroup.agents.length < 2) {
          elements.push(...wiGroup.agents.flatMap((a) => renderSessionAgentTree(a, 0)));
          continue;
        }

        const isCollapsed = collapsedWorkItems.has(wiGroup.workItemId);
        const totalCards = wiGroup.agents.reduce(
          (sum, a) => sum + countTreeNodes(a, sessionChildrenByParent), 0,
        );
        const runningCount = wiGroup.agents.filter((a) => treeHasRunning(a)).length;
        const failCount = wiGroup.agents.filter((a) => !treeHasRunning(a) && treeHasFailure(a)).length;
        const okCount = wiGroup.agents.length - runningCount - failCount;

        const summaryParts: string[] = [];
        if (runningCount > 0) summaryParts.push(`${runningCount} running`);
        if (okCount > 0) summaryParts.push(`${okCount} ok`);
        if (failCount > 0) summaryParts.push(`${failCount} failed`);

        elements.push(
          <WorkItemGroupSection
            key={`wi-${wiGroup.workItemId}`}
            workItemId={wiGroup.workItemId}
            workItemTitle={wiGroup.workItemTitle}
            totalCards={totalCards}
            isCollapsed={isCollapsed}
            summaryParts={summaryParts}
            onToggle={() => toggleInSet(setCollapsedWorkItems, wiGroup.workItemId)}
          >
            {wiGroup.agents.flatMap((a) => renderSessionAgentTree(a, 0))}
          </WorkItemGroupSection>,
        );
      }

      return elements;
    };

    const renderedActiveAgents = renderGroupedAgentSection(activeRootAgents);
    const renderedCompletedAgents = renderGroupedAgentSection(completedRootAgents);

    const completedFailedCount = completedRootAgents.filter(treeHasFailure).length;
    const completedSuccessCount = completedRootAgents.length - completedFailedCount;

    const isCompletedExpanded = expandedCompletedSections.has(group.sessionId);
    const isActiveExpanded = !collapsedActiveSections.has(group.sessionId);
    const activeSectionId = `active-agents-${group.sessionId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

    const renderedSections = (
      <div className="agent-sections">
        <div className="agent-section agent-section-active">
          <button
            className="agent-section-header"
            onClick={() => toggleInSet(setCollapsedActiveSections, group.sessionId)}
            aria-expanded={isActiveExpanded}
            aria-controls={isActiveExpanded ? activeSectionId : undefined}
            type="button"
          >
            <span className="agent-section-chevron">{isActiveExpanded ? "▾" : "▸"}</span>
            <span className="agent-section-label">Active agents</span>
            <span className="agent-section-count">{activeRootAgents.length}</span>
          </button>
          {isActiveExpanded ? (
            renderedActiveAgents.length > 0 ? (
              <div id={activeSectionId} className="agent-section-content">
                {renderedActiveAgents}
              </div>
            ) : (
              <div id={activeSectionId} className="agent-section-empty">
                No active agents
              </div>
            )
          ) : null}
        </div>

        {completedRootAgents.length > 0 ? (
          <div className="agent-section agent-section-completed">
            <button
              className="agent-section-header"
              onClick={() => toggleInSet(setExpandedCompletedSections, group.sessionId)}
              aria-expanded={isCompletedExpanded}
              type="button"
            >
              <span className="agent-section-chevron">{isCompletedExpanded ? "▾" : "▸"}</span>
              <span className="agent-section-label">Completed</span>
              <span className="agent-section-count">{completedRootAgents.length}</span>
              <span className="agent-section-summary">
                {completedFailedCount > 0
                  ? `${completedSuccessCount} ok · ${completedFailedCount} failed`
                  : `${completedSuccessCount} ok`}
              </span>
            </button>
            {isCompletedExpanded && <div className="agent-section-content">{renderedCompletedAgents}</div>}
          </div>
        ) : null}
      </div>
    );

    if (!hasMultipleSessions) {
      return <div key={group.sessionId}>{renderedSections}</div>;
    }

    const label = isCurrent ? "Current session" : formatSessionLabel(group.sessionId);

    return (
      <div key={group.sessionId} className="session-group">
        <button
          className={`session-group-header${isCurrent ? " session-group-current" : ""}`}
          onClick={() => !isCurrent && toggleInSet(setExpandedSessions, group.sessionId)}
          aria-expanded={isExpanded}
        >
          <span className="session-group-chevron">{isExpanded ? "▾" : "▸"}</span>
          <span className="session-group-label">{label}</span>
          <span className="session-group-count">{group.agents.length}</span>
        </button>
        {isExpanded && <div className="session-group-content">{renderedSections}</div>}
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
            title={
              spawnAtLimit ? "At max agent limit — increase max_parallel_agents in Settings" : "Spawn additional agent"
            }
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
              (currentSessionId == null && group === sessionGroups[sessionGroups.length - 1]),
          ),
        )}
      </div>
    </aside>
  );
}
