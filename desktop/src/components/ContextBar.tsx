/** Compact context window usage bar for an agent card. */

import { useEffect, useRef } from "react";

import { formatTokens } from "../utils/stats";

export function ContextBar({ inputTokens, outputTokens, contextLimit }: {
  inputTokens: number;
  outputTokens: number;
  contextLimit: number;
}) {
  const fillRef = useRef<HTMLDivElement>(null);
  const total = inputTokens + outputTokens;
  const pct = contextLimit > 0 ? Math.min((total / contextLimit) * 100, 100) : 0;
  const isWarning = pct >= 80;

  useEffect(() => {
    if (fillRef.current) {
      fillRef.current.style.width = `${pct}%`;
    }
  }, [pct]);

  return (
    <div className="agent-card-context" title={`Input: ${formatTokens(inputTokens)} · Output: ${formatTokens(outputTokens)}`}>
      <div className="agent-card-context-bar">
        <div
          ref={fillRef}
          className={`agent-card-context-fill${isWarning ? " agent-card-context-warn" : ""}`}
        />
      </div>
      <span className="agent-card-context-label">
        {formatTokens(total)}{contextLimit > 0 ? ` / ${formatTokens(contextLimit)}` : ""}
      </span>
    </div>
  );
}
