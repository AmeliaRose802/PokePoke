/**
 * Renders a parsed gate agent verdict as a structured card preview.
 *
 * Shows status (Passed/Failed), reason, detail message, and optional recommendation.
 */

import type { GateVerdict } from "../utils/agentHelpers";

interface Props {
  verdict: GateVerdict;
}

export function GateVerdictPreview({ verdict }: Props) {
  return (
    <div className="gate-verdict-preview">
      <div className={`gate-verdict-status gate-verdict-status-${verdict.status}`}>
        {verdict.status === "success" ? "✓ Passed" : "✗ Failed"}
      </div>
      {verdict.reason && (
        <div className="gate-verdict-reason">{verdict.reason}</div>
      )}
      {(verdict.message ?? verdict.details) && (
        <div className="gate-verdict-detail">
          {verdict.message ?? verdict.details}
        </div>
      )}
      {verdict.recommendation && (
        <div className="gate-verdict-recommendation">
          {verdict.recommendation}
        </div>
      )}
    </div>
  );
}
