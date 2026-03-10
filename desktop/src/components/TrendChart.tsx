interface TrendChartProps {
  title: string;
  data: { label: string; value: number }[];
  color: string;
  valueFormatter?: (value: number) => string;
  emptyLabel: string;
}

export function TrendChart({ title, data, color, valueFormatter, emptyLabel }: TrendChartProps) {
  if (!data.length) {
    return (
      <div className="stats-panel-card trend-card">
        <div className="stats-panel-card-header">
          <h3>{title}</h3>
        </div>
        <p className="stats-empty">{emptyLabel}</p>
      </div>
    );
  }

  const maxValue = Math.max(...data.map((d) => d.value), 1);
  const points = data.map((point, index) => {
    const x = data.length === 1 ? 50 : (index / (data.length - 1)) * 100;
    const normalized = maxValue === 0 ? 0 : (point.value / maxValue) * 100;
    const y = 100 - normalized;
    return `${x},${y}`;
  });

  return (
    <div className="stats-panel-card trend-card">
      <div className="stats-panel-card-header">
        <h3>{title}</h3>
      </div>
      <div className="trend-chart">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline fill="none" stroke={color} strokeWidth="2" points={points.join(" ")} />
        </svg>
        <ul className="trend-chart-labels">
          {data.map((point) => (
            <li key={point.label}>
              <span>{point.label}</span>
              <strong>{valueFormatter ? valueFormatter(point.value) : point.value}</strong>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
