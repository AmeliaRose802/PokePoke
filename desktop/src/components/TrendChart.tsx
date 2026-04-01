interface TrendChartProps {
  title: string;
  data: { label: string; value: number }[];
  color: string;
  valueFormatter?: (value: number) => string;
  emptyLabel: string;
}

// Chart layout constants
const CHART = {
  LEFT_MARGIN: 12, // Space for Y-axis labels
  RIGHT_MARGIN: 2,
  TOP_MARGIN: 8,
  BOTTOM_MARGIN: 4,
  Y_TICKS: 4, // Number of Y-axis tick marks
};

// Calculate nice round tick values for Y-axis
function calculateYTicks(maxValue: number, tickCount: number): number[] {
  if (maxValue === 0) return [0];
  const step = maxValue / tickCount;
  const magnitude = Math.pow(10, Math.floor(Math.log10(step)));
  const normalizedStep = step / magnitude;
  let niceStep: number;
  if (normalizedStep <= 1) niceStep = magnitude;
  else if (normalizedStep <= 2) niceStep = 2 * magnitude;
  else if (normalizedStep <= 5) niceStep = 5 * magnitude;
  else niceStep = 10 * magnitude;

  const ticks: number[] = [];
  for (let v = 0; v <= maxValue; v += niceStep) {
    ticks.push(v);
  }
  if (ticks[ticks.length - 1] < maxValue) {
    ticks.push(ticks[ticks.length - 1] + niceStep);
  }
  return ticks;
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
  const yTicks = calculateYTicks(maxValue, CHART.Y_TICKS);
  const yMax = yTicks[yTicks.length - 1] || maxValue;

  // Chart area bounds within viewBox
  const chartLeft = CHART.LEFT_MARGIN;
  const chartRight = 100 - CHART.RIGHT_MARGIN;
  const chartTop = CHART.TOP_MARGIN;
  const chartBottom = 100 - CHART.BOTTOM_MARGIN;
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;

  // Calculate points within the chart area
  const pointsData = data.map((point, index) => {
    const x = data.length === 1 ? chartLeft + chartWidth / 2 : chartLeft + (index / (data.length - 1)) * chartWidth;
    const normalized = yMax === 0 ? 0 : (point.value / yMax) * chartHeight;
    const y = chartBottom - normalized;
    return { x, y, value: point.value, label: point.label };
  });

  const polylinePoints = pointsData.map((p) => `${p.x},${p.y}`).join(" ");

  // Format value for display - compact format for annotations
  const formatValue = (v: number) => (valueFormatter ? valueFormatter(v) : String(v));

  // Generate dynamic CSS for X-axis label positions
  const xLabelStyles = data
    .map((_, index) => {
      const leftPos = chartLeft + (data.length === 1 ? chartWidth / 2 : (index / (data.length - 1)) * chartWidth);
      return `.trend-x-label-${index} { left: ${leftPos}%; }`;
    })
    .join("\n");

  return (
    <div className="stats-panel-card trend-card">
      <style>{xLabelStyles}</style>
      <div className="stats-panel-card-header">
        <h3>{title}</h3>
      </div>
      <div className="trend-chart">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" className="trend-chart-svg">
          {/* Y-axis gridlines */}
          {yTicks.map((tick) => {
            const y = chartBottom - (tick / yMax) * chartHeight;
            return (
              <line
                key={`grid-${tick}`}
                x1={chartLeft}
                y1={y}
                x2={chartRight}
                y2={y}
                className="trend-chart-gridline"
              />
            );
          })}

          {/* Y-axis labels */}
          {yTicks.map((tick) => {
            const y = chartBottom - (tick / yMax) * chartHeight;
            return (
              <text key={`label-${tick}`} x={chartLeft - 1} y={y + 0.8} className="trend-chart-y-label">
                {formatValue(tick)}
              </text>
            );
          })}

          {/* Data line */}
          <polyline fill="none" stroke={color} strokeWidth="1.5" points={polylinePoints} className="trend-chart-line" />

          {/* Data point markers with value annotations */}
          {pointsData.map((point, index) => (
            <g key={index}>
              <circle cx={point.x} cy={point.y} r="1.5" fill={color} className="trend-chart-point" />
              <text x={point.x} y={point.y - 2.5} className="trend-chart-annotation">
                {formatValue(point.value)}
              </text>
            </g>
          ))}
        </svg>

        {/* X-axis labels (dates) below the chart */}
        <div className="trend-chart-x-axis">
          {data.map((point, index) => (
            <span key={point.label} className={`trend-chart-x-label trend-x-label-${index}`}>
              {point.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
