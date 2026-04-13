/**
 * FlowchartView - visual pipeline diagram for agent progress.
 *
 * Renders a directed graph showing each agent's journey through the
 * orchestration pipeline: claim → worktree → AI → validation → complete/retry.
 * Pure CSS rendering — no external graph library required.
 */

import { useMemo } from "react";

import type { AgentInfo } from "../types";
import { buildFlowchartData, type FlowchartData, type FlowchartNode, stageIcon } from "../utils/agentFlowchart";

interface Props {
  agent: AgentInfo;
  allAgents: AgentInfo[];
}

function NodeBadge({ node }: { node: FlowchartNode }) {
  const icon = stageIcon(node.stage);
  return (
    <div
      className={`flowchart-node flowchart-node--${node.status} flowchart-node--${node.stage}`}
      title={node.detail ?? node.label}
      data-testid={`flowchart-node-${node.id}`}
    >
      <span className="flowchart-node-icon">{icon}</span>
      <span className="flowchart-node-label">{node.label}</span>
      {node.detail ? <span className="flowchart-node-detail">{node.detail}</span> : null}
    </div>
  );
}

function AttemptColumn({ nodes, attemptNum }: { nodes: FlowchartNode[]; attemptNum: number }) {
  return (
    <div className="flowchart-attempt" data-testid={`flowchart-attempt-${attemptNum}`}>
      {attemptNum > 1 && (
        <div className="flowchart-attempt-label">Attempt {attemptNum}</div>
      )}
      <div className="flowchart-attempt-nodes">
        {nodes.map((node) => (
          <div key={node.id} className="flowchart-step">
            <NodeBadge node={node} />
            {/* Edge connector to next node (except last) */}
            {node !== nodes[nodes.length - 1] && (
              <div className={`flowchart-edge flowchart-edge--${node.status}`}>
                <span className="flowchart-edge-line" />
                <span className="flowchart-edge-arrow">▾</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function RetryConnector({ label }: { label?: string }) {
  return (
    <div className="flowchart-retry-connector">
      <div className="flowchart-retry-arrow">
        <span className="flowchart-retry-curve" />
        <span className="flowchart-retry-label">{label ?? "Retry with feedback"}</span>
        <span className="flowchart-retry-curve" />
      </div>
    </div>
  );
}

export function FlowchartView({ agent, allAgents }: Props) {
  const flowchart: FlowchartData = useMemo(
    () => buildFlowchartData(agent, allAgents),
    [agent, allAgents],
  );

  // Group nodes by attempt
  const attemptGroups = useMemo(() => {
    const groups = new Map<number, FlowchartNode[]>();
    for (const node of flowchart.nodes) {
      const attempt = node.attempt ?? 1;
      const group = groups.get(attempt) ?? [];
      group.push(node);
      groups.set(attempt, group);
    }
    return Array.from(groups.entries()).sort(([a], [b]) => a - b);
  }, [flowchart.nodes]);

  return (
    <div className="flowchart-view" data-testid="flowchart-view">
      <div className="flowchart-header">
        <span className="flowchart-title">Pipeline Progress</span>
        {flowchart.totalAttempts > 1 && (
          <span className="flowchart-attempts-badge">
            {flowchart.totalAttempts} attempts
          </span>
        )}
      </div>
      <div className="flowchart-body">
        {attemptGroups.map(([attemptNum, nodes], idx) => (
          <div key={attemptNum} className="flowchart-attempt-wrapper">
            {idx > 0 && <RetryConnector />}
            <AttemptColumn nodes={nodes} attemptNum={attemptNum} />
          </div>
        ))}
      </div>
    </div>
  );
}
