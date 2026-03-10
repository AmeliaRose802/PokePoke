import { useState } from "react";

import { formatDurationWithSpread, formatPercent, formatTokens } from "../utils/stats";

interface ModelTableRow {
  model: string;
  runs: number;
  successRate: number;
  medianDuration: number;
  stddevDuration: number;
  tokens?: number;
}

type SortField = "model" | "runs" | "success" | "duration" | "tokens";

interface ModelTableProps {
  rows: ModelTableRow[];
  sortField: SortField;
  sortAsc: boolean;
  onSort: (field: SortField) => void;
  emptyMessage?: string;
  collapsedCount?: number;
}

export function ModelTable({
  rows,
  sortField,
  sortAsc,
  onSort,
  emptyMessage = "No model history yet.",
  collapsedCount = 5,
}: ModelTableProps) {
  const [expanded, setExpanded] = useState(false);

  if (rows.length === 0) {
    return <p className="stats-empty">{emptyMessage}</p>;
  }

  const hasMoreRows = rows.length > collapsedCount;
  const displayedRows = expanded ? rows : rows.slice(0, collapsedCount);
  const hiddenCount = rows.length - collapsedCount;

  return (
    <div className="model-table-wrapper">
      <table className="model-table">
        <thead>
          <tr>
            <SortableHead label="Model" field="model" activeField={sortField} asc={sortAsc} onSort={onSort} />
            <SortableHead label="Runs" field="runs" activeField={sortField} asc={sortAsc} onSort={onSort} />
            <SortableHead label="Success rate" field="success" activeField={sortField} asc={sortAsc} onSort={onSort} />
            <SortableHead label="Duration" field="duration" activeField={sortField} asc={sortAsc} onSort={onSort} />
            <SortableHead label="Tokens" field="tokens" activeField={sortField} asc={sortAsc} onSort={onSort} />
          </tr>
        </thead>
        <tbody>
          {displayedRows.map((row) => (
            <tr key={row.model}>
              <td>{row.model}</td>
              <td>{row.runs}</td>
              <td>
                <SuccessBar value={row.successRate} label={formatPercent(row.successRate, 1)} />
              </td>
              <td>{formatDurationWithSpread(row.medianDuration, row.stddevDuration)}</td>
              <td>{row.tokens !== undefined ? formatTokens(row.tokens) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasMoreRows && (
        <button type="button" className="model-table-expand-btn" onClick={() => setExpanded((prev) => !prev)}>
          {expanded ? "Show less" : `Show ${hiddenCount} more model${hiddenCount === 1 ? "" : "s"}`}
        </button>
      )}
    </div>
  );
}

function SortableHead({
  label,
  field,
  activeField,
  asc,
  onSort,
}: {
  label: string;
  field: SortField;
  activeField: SortField;
  asc: boolean;
  onSort: (field: SortField) => void;
}) {
  const isActive = activeField === field;
  return (
    <th>
      <button type="button" className={`sort-head ${isActive ? "active" : ""}`} onClick={() => onSort(field)}>
        {label}
        {isActive && <span className="sort-indicator">{asc ? "↑" : "↓"}</span>}
      </button>
    </th>
  );
}

function SuccessBar({ value, label }: { value: number; label: string }) {
  const percent = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="success-bar">
      <svg viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
        <rect className="success-bar-track" x={0} y={0} width={100} height={8} rx={4} ry={4} />
        <rect className="success-bar-progress" x={0} y={0} width={percent} height={8} rx={4} ry={4} />
      </svg>
      <span className="success-bar-label">{label}</span>
    </div>
  );
}
