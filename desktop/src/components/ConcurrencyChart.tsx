import type { ConcurrencyTimeline } from "../types";

interface ConcurrencyChartProps {
  data: ConcurrencyTimeline;
}

const CHART = {
  LEFT_MARGIN: 12,
  RIGHT_MARGIN: 2,
  TOP_MARGIN: 8,
  BOTTOM_MARGIN: 4,
  Y_TICKS: 4,
};

const COLORS = {
  activeLine: "#7aa2f7",
  maxLine: "#565f89",
  completionDot: "#9ece6a",
  failureDot: "#f7768e",
  areaFill: "rgba(122, 162, 247, 0.15)",
};

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

/** Parse "YYYY-MM-DD HH:MM:SS" into epoch seconds */
function parseTs(ts: string): number {
  return new Date(ts.replace(" ", "T")).getTime() / 1000;
}

/** Format epoch seconds as "HH:MM" */
function formatTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function ConcurrencyChart({ data }: ConcurrencyChartProps) {
  const { lifecycle, completions, failures } = data;

  if (lifecycle.length === 0) {
    return (
      <div className="stats-panel-card concurrency-card">
        <div className="stats-panel-card-header">
          <h3>Concurrent agents over time</h3>
          <span className="stats-panel-subtitle">Active agent count, completions, and failures</span>
        </div>
        <p className="stats-empty">No lifecycle data yet</p>
      </div>
    );
  }

  // Parse timestamps to epoch seconds
  const lifecycleParsed = lifecycle.map((e) => ({ ...e, epoch: parseTs(e.ts) }));
  const completionsParsed = completions.map((e) => ({ ...e, epoch: parseTs(e.ts) }));
  const failuresParsed = failures.map((e) => ({ ...e, epoch: parseTs(e.ts) }));

  const minTime = lifecycleParsed[0].epoch;
  const maxTime = lifecycleParsed[lifecycleParsed.length - 1].epoch;
  const timeRange = maxTime - minTime || 1;

  const maxActive = Math.max(...lifecycleParsed.map((e) => e.active), 1);
  const maxMax = Math.max(...lifecycleParsed.map((e) => e.max), maxActive);
  const yTicks = calculateYTicks(maxMax, CHART.Y_TICKS);
  const yMax = yTicks[yTicks.length - 1] || maxMax;

  const chartLeft = CHART.LEFT_MARGIN;
  const chartRight = 100 - CHART.RIGHT_MARGIN;
  const chartTop = CHART.TOP_MARGIN;
  const chartBottom = 100 - CHART.BOTTOM_MARGIN;
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;

  const toX = (epoch: number) => chartLeft + ((epoch - minTime) / timeRange) * chartWidth;
  const toY = (value: number) => chartBottom - (value / yMax) * chartHeight;

  // Active line points (step function for accurate representation)
  const activePoints: string[] = [];
  for (let i = 0; i < lifecycleParsed.length; i++) {
    const p = lifecycleParsed[i];
    const x = toX(p.epoch);
    const y = toY(p.active);
    if (i > 0) {
      // Step: horizontal segment to this point's X at previous Y
      activePoints.push(`${x},${toY(lifecycleParsed[i - 1].active)}`);
    }
    activePoints.push(`${x},${y}`);
  }

  // Area fill path (under the active line)
  const areaPath = [
    `M ${toX(lifecycleParsed[0].epoch)},${chartBottom}`,
    ...lifecycleParsed.flatMap((p, i) => {
      const x = toX(p.epoch);
      const y = toY(p.active);
      if (i > 0) {
        return [
          `L ${x},${toY(lifecycleParsed[i - 1].active)}`,
          `L ${x},${y}`,
        ];
      }
      return [`L ${x},${y}`];
    }),
    `L ${toX(lifecycleParsed[lifecycleParsed.length - 1].epoch)},${chartBottom}`,
    "Z",
  ].join(" ");

  // Max capacity line
  const maxPoints = lifecycleParsed.map((p) => `${toX(p.epoch)},${toY(p.max)}`).join(" ");

  // Map events to chart coordinates. Snap Y to active count at the nearest lifecycle entry.
  const findActiveAt = (epoch: number): number => {
    let closest = lifecycleParsed[0];
    for (const entry of lifecycleParsed) {
      if (entry.epoch <= epoch) closest = entry;
      else break;
    }
    return closest.active;
  };

  // X-axis time labels (pick ~5 evenly spaced labels)
  const xLabelCount = Math.min(5, lifecycleParsed.length);
  const xLabels: { epoch: number; label: string; leftPercent: number }[] = [];
  for (let i = 0; i < xLabelCount; i++) {
    const frac = xLabelCount === 1 ? 0.5 : i / (xLabelCount - 1);
    const epoch = minTime + frac * timeRange;
    xLabels.push({
      epoch,
      label: formatTime(epoch),
      leftPercent: chartLeft + frac * chartWidth,
    });
  }

  const xLabelStyles = xLabels
    .map((lbl, i) => `.concurrency-x-label-${i} { left: ${lbl.leftPercent}%; }`)
    .join("\n");

  return (
    <div className="stats-panel-card concurrency-card">
      <style>{xLabelStyles}</style>
      <div className="stats-panel-card-header">
        <h3>Concurrent agents over time</h3>
        <span className="stats-panel-subtitle">Active agent count, completions, and failures</span>
      </div>
      <div className="concurrency-chart">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" className="concurrency-chart-svg">
          {/* Y-axis gridlines */}
          {yTicks.map((tick) => {
            const y = toY(tick);
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
            const y = toY(tick);
            return (
              <text key={`label-${tick}`} x={chartLeft - 1} y={y + 0.8} className="trend-chart-y-label">
                {tick}
              </text>
            );
          })}

          {/* Area fill under active line */}
          <path d={areaPath} fill={COLORS.areaFill} />

          {/* Max capacity dashed line */}
          <polyline
            fill="none"
            stroke={COLORS.maxLine}
            strokeWidth="0.8"
            strokeDasharray="2,2"
            points={maxPoints}
            className="concurrency-max-line"
          />

          {/* Active agents step line */}
          <polyline
            fill="none"
            stroke={COLORS.activeLine}
            strokeWidth="1.5"
            points={activePoints.join(" ")}
            className="concurrency-active-line"
          />

          {/* Completion events (green dots) */}
          {completionsParsed.map((evt, i) => {
            const x = toX(evt.epoch);
            const y = toY(findActiveAt(evt.epoch));
            return (
              <circle
                key={`c-${i}`}
                cx={x}
                cy={y}
                r="1.8"
                fill={COLORS.completionDot}
                className="concurrency-event-dot"
              >
                <title>✅ Completed: {evt.item_id}</title>
              </circle>
            );
          })}

          {/* Failure events (red dots) */}
          {failuresParsed.map((evt, i) => {
            const x = toX(evt.epoch);
            const y = toY(findActiveAt(evt.epoch));
            return (
              <circle
                key={`f-${i}`}
                cx={x}
                cy={y}
                r="1.8"
                fill={COLORS.failureDot}
                className="concurrency-event-dot"
              >
                <title>❌ Failed: {evt.item_id}</title>
              </circle>
            );
          })}
        </svg>

        {/* X-axis time labels */}
        <div className="concurrency-chart-x-axis">
          {xLabels.map((lbl, i) => (
            <span key={lbl.label} className={`concurrency-chart-x-label concurrency-x-label-${i}`}>
              {lbl.label}
            </span>
          ))}
        </div>

        {/* Legend */}
        <div className="concurrency-legend">
          <span className="concurrency-legend-item">
            <svg viewBox="0 0 12 8" className="concurrency-legend-icon" aria-hidden="true">
              <line x1="0" y1="4" x2="12" y2="4" stroke={COLORS.activeLine} strokeWidth="2" />
            </svg>
            Active
          </span>
          <span className="concurrency-legend-item">
            <svg viewBox="0 0 12 8" className="concurrency-legend-icon" aria-hidden="true">
              <line x1="0" y1="4" x2="12" y2="4" stroke={COLORS.maxLine} strokeWidth="1.5" strokeDasharray="3,2" />
            </svg>
            Max
          </span>
          <span className="concurrency-legend-item">
            <svg viewBox="0 0 8 8" className="concurrency-legend-icon" aria-hidden="true">
              <circle cx="4" cy="4" r="3.5" fill={COLORS.completionDot} />
            </svg>
            Completed
          </span>
          <span className="concurrency-legend-item">
            <svg viewBox="0 0 8 8" className="concurrency-legend-icon" aria-hidden="true">
              <circle cx="4" cy="4" r="3.5" fill={COLORS.failureDot} />
            </svg>
            Failed
          </span>
        </div>
      </div>
    </div>
  );
}
