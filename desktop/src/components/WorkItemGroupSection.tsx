/** Collapsible work item group header for grouping agent cards. */

import type { ReactNode } from "react";

interface Props {
  workItemId: string;
  workItemTitle: string;
  totalCards: number;
  isCollapsed: boolean;
  summaryParts: string[];
  onToggle: () => void;
  children: ReactNode;
}

export function WorkItemGroupSection({
  workItemId,
  workItemTitle,
  totalCards,
  isCollapsed,
  summaryParts,
  onToggle,
  children,
}: Props) {
  return (
    <div className="work-item-group">
      <button
        className="work-item-group-header"
        onClick={onToggle}
        aria-expanded={!isCollapsed}
        type="button"
      >
        <span className="work-item-group-chevron">{isCollapsed ? "▸" : "▾"}</span>
        <span className="work-item-group-label">
          📋 {workItemTitle || workItemId}
        </span>
        <span className="work-item-group-count">
          {totalCards} {totalCards === 1 ? "card" : "cards"}
        </span>
        {isCollapsed && summaryParts.length > 0 && (
          <span className="work-item-group-summary">{summaryParts.join(" · ")}</span>
        )}
      </button>
      {!isCollapsed && (
        <div className="work-item-group-content">
          {children}
        </div>
      )}
    </div>
  );
}
