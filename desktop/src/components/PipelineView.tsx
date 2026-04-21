/**
 * PipelineView — unified end-to-end orchestration visualization.
 *
 * Shows the full work-item lifecycle as a two-phase pipeline:
 *   Phase 1: Quality Gate (work agent → cleanup → gate agent → approve/retry)
 *   Phase 2: Merge Workflow (lock → validate → merge → cleanup)
 *
 * Each phase shows a status indicator (pending/active/done/failed) and
 * expands to the detailed flowchart via MergeFlowchartView.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { MergeFlowState, PipelineState } from "../types";
import { MergeFlowchartView } from "./MergeFlowchartView";

interface Props {
  getPipelineState: () => Promise<PipelineState | null>;
  getMergeFlowState: () => Promise<MergeFlowState | null>;
  getGateFlowState: () => Promise<MergeFlowState | null>;
}

type PhaseStatus = "pending" | "active" | "done" | "failed";

function derivePhaseStatus(flow: MergeFlowState | null): PhaseStatus {
  if (!flow) return "pending";
  const run = flow.current_run ?? flow.last_completed_run;
  if (!run) return "pending";
  if (flow.current_run) return "active";
  if (run.outcome === "success") return "done";
  if (run.outcome === "failed") return "failed";
  return "pending";
}

function phaseIcon(status: PhaseStatus): string {
  switch (status) {
    case "done": return "✅";
    case "active": return "⏳";
    case "failed": return "❌";
    default: return "○";
  }
}

function phaseLabel(status: PhaseStatus): string {
  switch (status) {
    case "done": return "Complete";
    case "active": return "Active";
    case "failed": return "Failed";
    default: return "Pending";
  }
}

export function PipelineView({ getPipelineState, getMergeFlowState, getGateFlowState }: Props) {
  const [pipelineState, setPipelineState] = useState<PipelineState | null>(null);
  const [expandedPhase, setExpandedPhase] = useState<"gate" | "merge" | null>(null);
  const prevActivePhaseRef = useRef<string | null>(null);

  // Auto-expand when active phase changes (handled inside poll to avoid setState-in-effect)
  useEffect(() => {
    let stopped = false;

    async function poll() {
      while (!stopped) {
        try {
          const state = await getPipelineState();
          if (!stopped && state) {
            setPipelineState(state);
            // Auto-expand when active phase transitions
            const newPhase = state.active_phase;
            if ((newPhase === "gate" || newPhase === "merge") && newPhase !== prevActivePhaseRef.current) {
              setExpandedPhase(newPhase);
            }
            prevActivePhaseRef.current = newPhase;
          }
        } catch {
          // Silently ignore poll errors
        }
        await new Promise((r) => setTimeout(r, 500));
      }
    }

    poll();
    return () => { stopped = true; };
  }, [getPipelineState]);

  const togglePhase = useCallback((phase: "gate" | "merge") => {
    setExpandedPhase((prev) => (prev === phase ? null : phase));
  }, []);

  const gateStatus = derivePhaseStatus(pipelineState?.gate ?? null);
  const mergeStatus = derivePhaseStatus(pipelineState?.merge ?? null);

  const gateRun = pipelineState?.gate?.current_run ?? pipelineState?.gate?.last_completed_run;

  return (
    <div className="pipeline-view" data-testid="pipeline-view">
      <div className="pipeline-header">
        <span className="pipeline-title">🔄 Pipeline</span>
        {gateRun && (
          <span className="pipeline-context">
            {gateRun.agent_id} — {gateRun.item_id}
          </span>
        )}
      </div>

      <div className="pipeline-phases">
        {/* Phase 1: Quality Gate */}
        <div className={`pipeline-phase pipeline-phase--${gateStatus}`} data-testid="pipeline-phase-gate">
          <button
            className={`pipeline-phase-header${expandedPhase === "gate" ? " pipeline-phase-header--expanded" : ""}`}
            onClick={() => togglePhase("gate")}
            data-testid="pipeline-phase-gate-toggle"
          >
            <span className="pipeline-phase-indicator">
              <span className={`pipeline-phase-dot pipeline-phase-dot--${gateStatus}`} />
            </span>
            <span className="pipeline-phase-icon">🔍</span>
            <span className="pipeline-phase-label">Quality Gate</span>
            <span className={`pipeline-phase-status pipeline-phase-status--${gateStatus}`}>
              {phaseIcon(gateStatus)} {phaseLabel(gateStatus)}
            </span>
            <span className="pipeline-phase-chevron">{expandedPhase === "gate" ? "▲" : "▼"}</span>
          </button>
          {expandedPhase === "gate" && (
            <div className="pipeline-phase-content" data-testid="pipeline-phase-gate-content">
              <MergeFlowchartView
                getMergeFlowState={getGateFlowState}
                title="Quality Gate"
                icon="🔍"
                testIdPrefix="gate"
                emptyLabel="No gate activity yet."
              />
            </div>
          )}
        </div>

        {/* Connector between phases */}
        <div className={`pipeline-connector pipeline-connector--${gateStatus === "done" ? "active" : "pending"}`} data-testid="pipeline-connector">
          <span className="pipeline-connector-line" />
          <span className="pipeline-connector-arrow">▾</span>
          {gateStatus === "done" && <span className="pipeline-connector-label">Approved</span>}
        </div>

        {/* Phase 2: Merge Workflow */}
        <div className={`pipeline-phase pipeline-phase--${mergeStatus}`} data-testid="pipeline-phase-merge">
          <button
            className={`pipeline-phase-header${expandedPhase === "merge" ? " pipeline-phase-header--expanded" : ""}`}
            onClick={() => togglePhase("merge")}
            data-testid="pipeline-phase-merge-toggle"
          >
            <span className="pipeline-phase-indicator">
              <span className={`pipeline-phase-dot pipeline-phase-dot--${mergeStatus}`} />
            </span>
            <span className="pipeline-phase-icon">🔀</span>
            <span className="pipeline-phase-label">Merge Workflow</span>
            <span className={`pipeline-phase-status pipeline-phase-status--${mergeStatus}`}>
              {phaseIcon(mergeStatus)} {phaseLabel(mergeStatus)}
            </span>
            <span className="pipeline-phase-chevron">{expandedPhase === "merge" ? "▲" : "▼"}</span>
          </button>
          {expandedPhase === "merge" && (
            <div className="pipeline-phase-content" data-testid="pipeline-phase-merge-content">
              <MergeFlowchartView
                getMergeFlowState={getMergeFlowState}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
