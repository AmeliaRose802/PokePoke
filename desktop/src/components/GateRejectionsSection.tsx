import type { GateRejectionStats } from "../types";

export function GateRejectionsSection({ gateStats }: { gateStats: GateRejectionStats }) {
  const { per_model, per_item, totals } = gateStats;
  const modelEntries = Object.entries(per_model).sort(
    (a, b) => b[1].rejection_rate - a[1].rejection_rate,
  );
  const itemEntries = Object.entries(per_item)
    .filter(([, s]) => s.rejections > 0)
    .sort((a, b) => b[1].rejections - a[1].rejections);

  return (
    <section>
      <div className="stats-panel-card">
        <div className="stats-panel-card-header">
          <h3>Gate rejections</h3>
          <span className="stats-panel-subtitle">
            {totals.total_rejections} rejection{totals.total_rejections !== 1 ? "s" : ""} across{" "}
            {totals.total_checks} checks ({(totals.rejection_rate * 100).toFixed(0)}%)
          </span>
        </div>

        {modelEntries.length > 0 && (
          <div className="gate-rejection-subsection">
            <h4>By gate model</h4>
            <div className="gate-rejection-table" role="table">
              <div className="gate-rejection-header" role="row">
                <span role="columnheader">Model</span>
                <span role="columnheader">Checks</span>
                <span role="columnheader">Rejected</span>
                <span role="columnheader">Rate</span>
                <span role="columnheader">Trend</span>
              </div>
              {modelEntries.map(([model, s]) => (
                <div key={model} className="gate-rejection-row" role="row">
                  <span className="gate-rejection-model" title={model}>
                    {model.length > 25 ? `${model.slice(0, 25)}…` : model}
                  </span>
                  <span>{s.total_checks}</span>
                  <span>{s.total_rejected}</span>
                  <span className={s.rejection_rate > 0.3 ? "status-fail" : s.rejection_rate > 0 ? "status-neutral" : "status-pass"}>
                    {(s.rejection_rate * 100).toFixed(0)}%
                  </span>
                  <span className="gate-rejection-trend">
                    {(s.trend ?? []).slice(-20).map((t, i) => (
                      <span key={i} title={t.timestamp?.slice(0, 19)}>
                        {t.passed ? "✓" : "✗"}
                      </span>
                    ))}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {itemEntries.length > 0 && (
          <div className="gate-rejection-subsection">
            <h4>Items with rejections</h4>
            <div className="gate-rejection-table" role="table">
              <div className="gate-rejection-header" role="row">
                <span role="columnheader">Item</span>
                <span role="columnheader">Checks</span>
                <span role="columnheader">Rejected</span>
                <span role="columnheader">Models</span>
              </div>
              {itemEntries.slice(0, 20).map(([itemId, s]) => (
                <div key={itemId} className="gate-rejection-row" role="row">
                  <span className="gate-rejection-model" title={itemId}>
                    {itemId}
                  </span>
                  <span>{s.total_checks}</span>
                  <span className="status-fail">{s.rejections}</span>
                  <span title={s.gate_models_used.join(", ")}>
                    {s.gate_models_used.length > 1
                      ? `${s.gate_models_used.length} models`
                      : s.gate_models_used[0] ?? "—"}
                  </span>
                </div>
              ))}
            </div>
            {itemEntries.length > 20 && (
              <span className="stats-panel-subtitle">
                Showing top 20 of {itemEntries.length} items with rejections
              </span>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
