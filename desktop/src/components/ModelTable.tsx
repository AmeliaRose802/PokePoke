import { formatDurationWithSpread, formatPercent } from "../utils/stats";

interface ModelTableRow {
  model: string;
  runs: number;
  successRate: number;
  medianDuration: number;
  stddevDuration: number;
}

type SortField = "model" | "runs" | "success" | "duration";

interface ModelTableProps {
  rows: ModelTableRow[];
  sortField: SortField;
  sortAsc: boolean;
  onSort: (field: SortField) => void;
  emptyMessage?: string;
}

export function ModelTable({
  rows,
  sortField,
  sortAsc,
  onSort,
  emptyMessage = "No model history yet.",
}: ModelTableProps) {
  if (rows.length === 0) {
    return <p className="stats-empty">{emptyMessage}</p>;
  }

  return (
    <div className="model-table-wrapper">
      <table className="model-table">
        <thead>
          <tr>
            <SortableHead
              label="Model"
              field="model"
              activeField={sortField}
              asc={sortAsc}
              onSort={onSort}
            />
            <SortableHead
              label="Runs"
              field="runs"
              activeField={sortField}
              asc={sortAsc}
              onSort={onSort}
            />
            <SortableHead
              label="Success rate"
              field="success"
              activeField={sortField}
              asc={sortAsc}
              onSort={onSort}
            />
            <SortableHead
              label="Duration"
              field="duration"
              activeField={sortField}
              asc={sortAsc}
              onSort={onSort}
            />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.model}>
              <td>{row.model}</td>
              <td>{row.runs}</td>
              <td>
                <SuccessBar
                  value={row.successRate}
                  label={formatPercent(row.successRate, 1)}
                />
              </td>
              <td>{formatDurationWithSpread(row.medianDuration, row.stddevDuration)}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
      <button
        type="button"
        className={`sort-head ${isActive ? "active" : ""}`}
        onClick={() => onSort(field)}
      >
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
        <rect
          className="success-bar-progress"
          x={0}
          y={0}
          width={percent}
          height={8}
          rx={4}
          ry={4}
        />
      </svg>
      <span className="success-bar-label">{label}</span>
    </div>
  );
}
