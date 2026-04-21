/**
 * MergeFlowchartView — live merge workflow visualization.
 *
 * Renders the merge pipeline steps (0–16) from docs/merge-workflow.md as an
 * interactive directed graph. Highlights the currently executing step, shows
 * success/fail coloring, and supports click-to-drill-down on step logs.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import type { MergeFlowRun, MergeFlowState, MergeStepDef, MergeStepStatus } from "../types";

interface Props {
  getMergeFlowState: () => Promise<MergeFlowState | null>;
  /** Display title (default: "Merge Workflow") */
  title?: string;
  /** Icon prefix (default: "🔀") */
  icon?: string;
  /** data-testid prefix (default: "merge") */
  testIdPrefix?: string;
  /** Label shown when no data (default: "No merge activity yet.") */
  emptyLabel?: string;
}

/** Map step status to a CSS modifier class */
function statusClass(status: MergeStepStatus): string {
  switch (status) {
    case "done":
      return "merge-node--done";
    case "active":
      return "merge-node--active";
    case "failed":
      return "merge-node--failed";
    case "skipped":
      return "merge-node--skipped";
    default:
      return "merge-node--pending";
  }
}

/** Icon for step status */
function statusIcon(status: MergeStepStatus): string {
  switch (status) {
    case "done":
      return "✅";
    case "active":
      return "⏳";
    case "failed":
      return "❌";
    case "skipped":
      return "⏭️";
    default:
      return "○";
  }
}

/** Format duration in seconds */
function formatDuration(startedAt: number | null, endedAt: number | null): string | null {
  if (startedAt == null) return null;
  const end = endedAt ?? Date.now() / 1000;
  const secs = end - startedAt;
  if (secs < 1) return "<1s";
  if (secs < 60) return `${Math.round(secs)}s`;
  return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`;
}

/** Step log drill-down panel */
function StepLogPanel({ step, onClose }: { step: { step_id: string; label: string; logs: string[]; status: MergeStepStatus }; onClose: () => void }) {
  return (
    <div className="merge-step-log-panel" data-testid="merge-step-log-panel">
      <div className="merge-step-log-header">
        <span className="merge-step-log-title">
          {statusIcon(step.status)} Step {step.step_id}: {step.label}
        </span>
        <button className="merge-step-log-close" onClick={onClose} title="Close log panel">
          ✕
        </button>
      </div>
      <div className="merge-step-log-body">
        {step.logs.length === 0 ? (
          <div className="merge-step-log-empty">No logs for this step yet.</div>
        ) : (
          step.logs.map((line, i) => (
            <div key={i} className="merge-step-log-line">
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export function MergeFlowchartView({ getMergeFlowState, title = "Merge Workflow", icon = "🔀", testIdPrefix = "merge", emptyLabel = "No merge activity yet." }: Props) {
  const [flowState, setFlowState] = useState<MergeFlowState | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);

  // Poll for merge flow state at 500ms intervals
  useEffect(() => {
    let stopped = false;

    async function poll() {
      while (!stopped) {
        try {
          const state = await getMergeFlowState();
          if (!stopped && state) setFlowState(state);
        } catch {
          // Silently ignore poll errors
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    }

    poll();
    return () => {
      stopped = true;
    };
  }, [getMergeFlowState]);

  // Determine which run to display: current (live) or last completed
  const displayRun: MergeFlowRun | null = useMemo(() => {
    if (!flowState) return null;
    return flowState.current_run ?? flowState.last_completed_run;
  }, [flowState]);

  const stepDefs: MergeStepDef[] = useMemo(() => flowState?.steps_definition ?? [], [flowState]);

  const isLive = flowState?.current_run != null;

  const handleStepClick = useCallback(
    (stepId: string) => {
      setSelectedStepId((prev) => (prev === stepId ? null : stepId));
    },
    [],
  );

  // Get selected step data
  const selectedStep = useMemo(() => {
    if (!selectedStepId || !displayRun) return null;
    return displayRun.steps[selectedStepId] ?? null;
  }, [selectedStepId, displayRun]);

  if (!flowState || !displayRun) {
    return (
      <div className="merge-flowchart-view" data-testid={`${testIdPrefix}-flowchart-view`}>
        <div className="merge-flowchart-header">
          <span className="merge-flowchart-title">{icon} {title}</span>
        </div>
        <div className="merge-flowchart-empty">{emptyLabel}</div>
      </div>
    );
  }

  return (
    <div className="merge-flowchart-view" data-testid={`${testIdPrefix}-flowchart-view`}>
      <div className="merge-flowchart-header">
        <span className="merge-flowchart-title">{icon} {title}</span>
        <span className={`merge-flowchart-status merge-flowchart-status--${displayRun.outcome}`}>
          {isLive ? "● Live" : displayRun.outcome === "success" ? "✓ Completed" : "✗ Failed"}
        </span>
        <span className="merge-flowchart-agent">
          Agent: {displayRun.agent_id} — Item: {displayRun.item_id}
        </span>
      </div>

      <div className="merge-flowchart-body">
        {/* Step nodes in pipeline order — only show steps that have been reached */}
        <div className="merge-flowchart-steps">
          {stepDefs.filter((def) => def.id in displayRun.steps).map((def, idx, visible) => {
            const stepState = displayRun.steps[def.id];
            const status: MergeStepStatus = stepState?.status ?? "pending";
            const duration = stepState ? formatDuration(stepState.started_at, stepState.ended_at) : null;
            const isSelected = selectedStepId === def.id;
            const hasLogs = (stepState?.logs.length ?? 0) > 0;

            return (
              <div key={def.id} className="merge-flowchart-step-wrapper">
                <button
                  className={`merge-node ${statusClass(status)}${isSelected ? " merge-node--selected" : ""}${hasLogs ? " merge-node--has-logs" : ""}`}
                  onClick={() => handleStepClick(def.id)}
                  title={`Step ${def.id}: ${def.label}${hasLogs ? " (click for logs)" : ""}`}
                  data-testid={`${testIdPrefix}-step-${def.id}`}
                >
                  <span className="merge-node-icon">{statusIcon(status)}</span>
                  <span className="merge-node-id">{def.id}</span>
                  <span className="merge-node-label">{def.label}</span>
                  {duration && <span className="merge-node-duration">{duration}</span>}
                </button>

                {/* Edge connector (except last visible step) */}
                {idx < visible.length - 1 && (
                  <div className={`merge-edge merge-edge--${status}`}>
                    <span className="merge-edge-line" />
                    <span className="merge-edge-arrow">▾</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Step log drill-down panel */}
      {selectedStep && (
        <StepLogPanel
          step={selectedStep}
          onClose={() => setSelectedStepId(null)}
        />
      )}
    </div>
  );
}
