import { formatDurationShort } from "../utils/stats";

interface CompletionTimeChartProps {
  data: Record<string, Array<{ label: string; value: number }>>;
  emptyLabel: string;
}

// Color palette for tags (cycle through these colors)
const tagColors = [
  "#7aa2f7", // blue
  "#9ece6a", // green
  "#f7768e", // red/pink
  "#e0af68", // orange
  "#bb9af7", // purple
  "#2ac3de", // cyan
  "#ff9e64", // orange
  "#c0caf5", // light blue
  "#565f89", // gray (for untagged)
];

const tagColorClasses = [
  "color-feature",
  "color-task",
  "color-bug",
  "color-unknown",
];

// Get color for a tag (consistent across renders)
function getTagColor(tag: string, index: number): string {
  if (tag === "untagged") return "#565f89"; // gray for untagged
  return tagColors[index % tagColors.length];
}

function getTagColorClass(tag: string, index: number): string {
  if (tag === "untagged") return "color-unknown";
  return tagColorClasses[index % tagColorClasses.length];
}

export function CompletionTimeChart({ data, emptyLabel }: CompletionTimeChartProps) {
  const hasData = Object.values(data).some((series) => series.length > 0);

  if (!hasData) {
    return <p className="stats-empty">{emptyLabel}</p>;
  }

  // Get all unique date labels
  const allLabels = new Set<string>();
  for (const series of Object.values(data)) {
    series.forEach((point) => allLabels.add(point.label));
  }
  const labels = Array.from(allLabels).sort();

  // Build normalized data for each tag
  const typeSeriesData: Array<{
    type: string;
    color: string;
    colorClass: string;
    values: number[];
    maxValue: number;
  }> = [];

  let tagIndex = 0;
  for (const [tag, series] of Object.entries(data)) {
    if (series.length === 0) continue;
    const valuesByLabel = new Map(series.map((p) => [p.label, p.value]));
    const values = labels.map((label) => valuesByLabel.get(label) ?? 0);
    const maxValue = Math.max(...values, 1);
    typeSeriesData.push({
      type: tag,
      color: getTagColor(tag, tagIndex),
      colorClass: getTagColorClass(tag, tagIndex),
      values,
      maxValue,
    });
    tagIndex++;
  }

  const overallMax = Math.max(...typeSeriesData.map((s) => s.maxValue), 1);

  return (
    <div>
      <div className="completion-time-chart">
        <svg viewBox={`0 0 100 ${typeSeriesData.length * 30 + 10}`} preserveAspectRatio="none">
          {typeSeriesData.map((typeSeries, typeIndex) => {
            const yOffset = typeIndex * 30 + 15;
            const points = typeSeries.values.map((value, index) => {
              const x = labels.length === 1 ? 50 : (index / (labels.length - 1)) * 100;
              const normalized = overallMax === 0 ? 0 : (value / overallMax) * 20;
              const y = yOffset - normalized;
              return `${x},${y}`;
            });

            return (
              <g key={typeSeries.type}>
                <polyline
                  fill="none"
                  stroke={typeSeries.color}
                  strokeWidth="1.5"
                  points={points.join(" ")}
                />
                {typeSeries.values.map((value, index) => (
                  <circle
                    key={index}
                    cx={(labels.length === 1 ? 50 : (index / (labels.length - 1)) * 100)}
                    cy={yOffset - (overallMax === 0 ? 0 : (value / overallMax) * 20)}
                    r="0.8"
                    fill={typeSeries.color}
                  />
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="completion-time-legend">
        <div className="completion-time-series">
          {typeSeriesData.map((typeSeries) => (
            <div key={typeSeries.type} className="completion-time-series-item">
              <span className="completion-time-label">
                <span
                  className={`completion-time-dot ${typeSeries.colorClass}`}
                  aria-hidden="true"
                />
                {typeSeries.type}
              </span>
              <div className="completion-time-values">
                {typeSeries.values.map((value, index) => (
                  <span key={index} className="completion-time-value">
                    <small>{labels[index]}</small>
                    <strong>{formatDurationShort(value)}</strong>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
