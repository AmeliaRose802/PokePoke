import type { ProcessSnapshot } from "../types";

interface ProcessUsageChartProps {
  data: ProcessSnapshot[];
}

// Chart layout constants
const CHART = {
  LEFT_MARGIN: 12, // Space for left Y-axis labels
  RIGHT_MARGIN: 12, // Space for right Y-axis labels
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

// Format timestamp to HH:MM format
function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  } catch {
    return timestamp;
  }
}

export function ProcessUsageChart({ data }: ProcessUsageChartProps) {
  if (!data.length) {
    return (
      <div className="process-usage-chart-empty">
        <p className="stats-empty">No process snapshots captured yet. Snapshots are taken every 60 seconds.</p>
      </div>
    );
  }

  // Calculate max values for scaling
  const maxMemory = Math.max(...data.map((d) => d.total_memory_mb), 1);
  const maxCount = Math.max(...data.map((d) => Math.max(d.copilot_count, d.child_count)), 1);
  const maxCpu = Math.max(...data.map((d) => d.cpu_percent ?? 0), 1);

  // Generate tick marks
  const memoryTicks = calculateYTicks(maxMemory, CHART.Y_TICKS);
  const countTicks = calculateYTicks(maxCount, CHART.Y_TICKS);
  const cpuTicks = calculateYTicks(maxCpu, CHART.Y_TICKS);
  const memoryMax = memoryTicks[memoryTicks.length - 1] || maxMemory;
  const countMax = countTicks[countTicks.length - 1] || maxCount;
  const cpuMax = cpuTicks[cpuTicks.length - 1] || maxCpu;

  // Chart area bounds within viewBox
  const chartLeft = CHART.LEFT_MARGIN;
  const chartRight = 100 - CHART.RIGHT_MARGIN;
  const chartTop = CHART.TOP_MARGIN;
  const chartBottom = 100 - CHART.BOTTOM_MARGIN;
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;

  // Calculate points for each metric
  const memoryPoints = data.map((point, index) => {
    const x = data.length === 1 ? chartLeft + chartWidth / 2 : chartLeft + (index / (data.length - 1)) * chartWidth;
    const normalized = memoryMax === 0 ? 0 : (point.total_memory_mb / memoryMax) * chartHeight;
    const y = chartBottom - normalized;
    return { x, y, value: point.total_memory_mb, label: formatTime(point.timestamp) };
  });

  const copilotCountPoints = data.map((point, index) => {
    const x = data.length === 1 ? chartLeft + chartWidth / 2 : chartLeft + (index / (data.length - 1)) * chartWidth;
    const normalized = countMax === 0 ? 0 : (point.copilot_count / countMax) * chartHeight;
    const y = chartBottom - normalized;
    return { x, y, value: point.copilot_count };
  });

  const childCountPoints = data.map((point, index) => {
    const x = data.length === 1 ? chartLeft + chartWidth / 2 : chartLeft + (index / (data.length - 1)) * chartWidth;
    const normalized = countMax === 0 ? 0 : (point.child_count / countMax) * chartHeight;
    const y = chartBottom - normalized;
    return { x, y, value: point.child_count };
  });

  const cpuPoints = data.map((point, index) => {
    const x = data.length === 1 ? chartLeft + chartWidth / 2 : chartLeft + (index / (data.length - 1)) * chartWidth;
    const cpuVal = point.cpu_percent ?? 0;
    const normalized = cpuMax === 0 ? 0 : (cpuVal / cpuMax) * chartHeight;
    const y = chartBottom - normalized;
    return { x, y, value: cpuVal };
  });

  const memoryPolyline = memoryPoints.map((p) => `${p.x},${p.y}`).join(" ");
  const copilotPolyline = copilotCountPoints.map((p) => `${p.x},${p.y}`).join(" ");
  const childPolyline = childCountPoints.map((p) => `${p.x},${p.y}`).join(" ");
  const cpuPolyline = cpuPoints.map((p) => `${p.x},${p.y}`).join(" ");

  // Generate dynamic CSS for X-axis label positions and legend dot colors
  const labelIndices = data.length <= 6 ? data.map((_, i) => i) : [0, Math.floor(data.length / 2), data.length - 1];
  const xLabelStyles = labelIndices
    .map((index) => {
      const leftPos = chartLeft + (data.length === 1 ? chartWidth / 2 : (index / (data.length - 1)) * chartWidth);
      return `.process-x-label-${index} { left: ${leftPos}%; }`;
    })
    .join("\n");

  const legendDotStyles = [
    ".process-legend-dot-cpu { background-color: #ff9e64; }",
    ".process-legend-dot-memory { background-color: #7aa2f7; }",
    ".process-legend-dot-copilot { background-color: #f7768e; }",
    ".process-legend-dot-child { background-color: #9ece6a; }",
  ].join("\n");

  return (
    <div className="process-usage-chart-container">
      <style>{xLabelStyles + "\n" + legendDotStyles}</style>
      <div className="process-usage-legend">
        <span className="process-legend-item">
          <span className="process-legend-dot process-legend-dot-cpu"></span>
          CPU %
        </span>
        <span className="process-legend-item">
          <span className="process-legend-dot process-legend-dot-memory"></span>
          Memory (MB)
        </span>
        <span className="process-legend-item">
          <span className="process-legend-dot process-legend-dot-copilot"></span>
          Copilot Processes
        </span>
        <span className="process-legend-item">
          <span className="process-legend-dot process-legend-dot-child"></span>
          Child Processes
        </span>
      </div>
      <div className="process-usage-chart">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" className="process-chart-svg">
          {/* Left Y-axis gridlines and labels (Memory MB) */}
          {memoryTicks.map((tick) => {
            const y = chartBottom - (tick / memoryMax) * chartHeight;
            return (
              <g key={`memory-grid-${tick}`}>
                <line
                  x1={chartLeft}
                  y1={y}
                  x2={chartRight}
                  y2={y}
                  className="process-chart-gridline"
                  stroke="#333"
                  strokeWidth="0.15"
                  opacity="0.3"
                />
                <text x={chartLeft - 1} y={y + 0.8} className="process-chart-y-label-left" fill="#7aa2f7" fontSize="3">
                  {Math.round(tick)}
                </text>
              </g>
            );
          })}

          {/* Right Y-axis labels (Process Count) */}
          {countTicks.map((tick) => {
            const y = chartBottom - (tick / countMax) * chartHeight;
            return (
              <text
                key={`count-label-${tick}`}
                x={chartRight + 1}
                y={y + 0.8}
                className="process-chart-y-label-right"
                fill="#f7768e"
                fontSize="3"
              >
                {Math.round(tick)}
              </text>
            );
          })}

          {/* Memory line (blue) */}
          <polyline
            fill="none"
            stroke="#7aa2f7"
            strokeWidth="1.5"
            points={memoryPolyline}
            className="process-chart-line"
          />

          {/* Copilot count line (red) */}
          <polyline
            fill="none"
            stroke="#f7768e"
            strokeWidth="1.5"
            points={copilotPolyline}
            className="process-chart-line"
          />

          {/* Child count line (green) */}
          <polyline
            fill="none"
            stroke="#9ece6a"
            strokeWidth="1.5"
            points={childPolyline}
            className="process-chart-line"
          />

          {/* CPU usage line (orange) */}
          <polyline
            fill="none"
            stroke="#ff9e64"
            strokeWidth="1.5"
            points={cpuPolyline}
            className="process-chart-line"
          />

          {/* Data point markers */}
          {memoryPoints.map((point, index) => (
            <circle
              key={`memory-${index}`}
              cx={point.x}
              cy={point.y}
              r="1"
              fill="#7aa2f7"
              className="process-chart-point"
            />
          ))}
          {copilotCountPoints.map((point, index) => (
            <circle
              key={`copilot-${index}`}
              cx={point.x}
              cy={point.y}
              r="1"
              fill="#f7768e"
              className="process-chart-point"
            />
          ))}
          {childCountPoints.map((point, index) => (
            <circle
              key={`child-${index}`}
              cx={point.x}
              cy={point.y}
              r="1"
              fill="#9ece6a"
              className="process-chart-point"
            />
          ))}
          {cpuPoints.map((point, index) => (
            <circle
              key={`cpu-${index}`}
              cx={point.x}
              cy={point.y}
              r="1"
              fill="#ff9e64"
              className="process-chart-point"
            />
          ))}
        </svg>

        {/* X-axis labels (timestamps) below the chart */}
        <div className="process-chart-x-axis">
          {labelIndices.map((index) => (
            <span key={index} className={`process-chart-x-label process-x-label-${index}`}>
              {memoryPoints[index].label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
