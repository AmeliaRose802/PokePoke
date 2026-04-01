import { useState } from "react";

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

// Get color for a tag (consistent across renders)
function getTagColor(tag: string, index: number): string {
  if (tag === "untagged") return "#565f89"; // gray for untagged
  return tagColors[index % tagColors.length];
}

interface TagSeriesData {
  type: string;
  color: string;
  values: number[];
  maxValue: number;
  avgValue: number;
  totalPoints: number;
}

// Chart layout constants
const CHART = {
  LEFT_MARGIN: 12, // Space for Y-axis labels
  RIGHT_MARGIN: 2,
  TOP_MARGIN: 6,
  BOTTOM_MARGIN: 4,
};

export function CompletionTimeChart({ data, emptyLabel }: CompletionTimeChartProps) {
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
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
  const allSeriesData: TagSeriesData[] = [];

  let tagIndex = 0;
  for (const [tag, series] of Object.entries(data)) {
    if (series.length === 0) continue;
    const valuesByLabel = new Map(series.map((p) => [p.label, p.value]));
    const values = labels.map((label) => valuesByLabel.get(label) ?? 0);
    const nonZero = values.filter((v) => v > 0);
    const avgValue = nonZero.length > 0 ? nonZero.reduce((a, b) => a + b, 0) / nonZero.length : 0;
    const maxValue = Math.max(...values, 1);
    allSeriesData.push({
      type: tag,
      color: getTagColor(tag, tagIndex),
      values,
      maxValue,
      avgValue,
      totalPoints: nonZero.length,
    });
    tagIndex++;
  }

  // Filter to selected tag or show all
  const visibleSeries = selectedTag ? allSeriesData.filter((s) => s.type === selectedTag) : allSeriesData;

  const overallMax = Math.max(...visibleSeries.map((s) => s.maxValue), 1);

  // Sort tag cloud by total data points (most active tags appear larger)
  const sortedTags = [...allSeriesData].sort((a, b) => b.totalPoints - a.totalPoints);
  const maxPoints = Math.max(...sortedTags.map((s) => s.totalPoints), 1);

  const handleTagClick = (tag: string) => {
    setSelectedTag((prev) => (prev === tag ? null : tag));
  };

  // Generate dynamic CSS for tag colors (avoids inline style prop forbidden by ESLint)
  const tagStyleRules = sortedTags
    .map((series, idx) => {
      const cls = `tag-chip-${idx}`;
      const scale = 0.75 + (series.totalPoints / maxPoints) * 0.5;
      return [
        `.${cls} { border-color: ${series.color}; font-size: ${scale}rem; }`,
        `.${cls}.tag-cloud-chip-active { background-color: ${series.color}; color: #1a1b26; }`,
        `.${cls} .tag-cloud-dot { background-color: ${series.color}; }`,
      ].join("\n");
    })
    .join("\n");

  // Chart area bounds
  const chartLeft = CHART.LEFT_MARGIN;
  const chartRight = 100 - CHART.RIGHT_MARGIN;
  const chartWidth = chartRight - chartLeft;
  const seriesHeight = 25;
  const totalHeight = visibleSeries.length * seriesHeight + CHART.TOP_MARGIN + CHART.BOTTOM_MARGIN;

  // Generate dynamic CSS for X-axis label positions
  const xLabelStyles = labels
    .map((_, index) => {
      const leftPos = chartLeft + (labels.length === 1 ? chartWidth / 2 : (index / (labels.length - 1)) * chartWidth);
      return `.ct-x-label-${index} { left: ${leftPos}%; }`;
    })
    .join("\n");

  return (
    <div>
      <style>{tagStyleRules + "\n" + xLabelStyles}</style>
      {/* Tag cloud for filtering */}
      <div className="tag-cloud" role="listbox" aria-label="Filter by tag">
        {sortedTags.map((series, idx) => {
          const isActive = selectedTag === series.type;
          const isDimmed = selectedTag !== null && !isActive;
          return (
            <button
              key={series.type}
              type="button"
              role="option"
              aria-selected={isActive}
              className={`tag-cloud-chip tag-chip-${idx}${isActive ? " tag-cloud-chip-active" : ""}${isDimmed ? " tag-cloud-chip-dimmed" : ""}`}
              onClick={() => handleTagClick(series.type)}
              title={`${series.type}: avg ${formatDurationShort(series.avgValue)}`}
            >
              <span className="tag-cloud-dot" aria-hidden="true" />
              {series.type}
              <span className="tag-cloud-avg">{formatDurationShort(series.avgValue)}</span>
            </button>
          );
        })}
        {selectedTag && (
          <button type="button" className="tag-cloud-clear" onClick={() => setSelectedTag(null)}>
            ✕ Clear filter
          </button>
        )}
      </div>

      {/* Chart lines */}
      <div className="completion-time-chart">
        <svg viewBox={`0 0 100 ${totalHeight}`} preserveAspectRatio="xMidYMid meet">
          {visibleSeries.map((typeSeries, typeIndex) => {
            const yBaseline = CHART.TOP_MARGIN + typeIndex * seriesHeight + seriesHeight * 0.7;
            const points = typeSeries.values.map((value, index) => {
              const x =
                labels.length === 1 ? chartLeft + chartWidth / 2 : chartLeft + (index / (labels.length - 1)) * chartWidth;
              const normalized = overallMax === 0 ? 0 : (value / overallMax) * (seriesHeight * 0.6);
              const y = yBaseline - normalized;
              return { x, y, value };
            });

            const polylinePoints = points.map((p) => `${p.x},${p.y}`).join(" ");

            return (
              <g key={typeSeries.type}>
                {/* Tag label on Y-axis */}
                <text
                  x={chartLeft - 1}
                  y={yBaseline - seriesHeight * 0.25}
                  className="completion-time-y-label"
                >
                  {typeSeries.type.length > 8 ? typeSeries.type.slice(0, 7) + "…" : typeSeries.type}
                </text>

                {/* Baseline reference line */}
                <line
                  x1={chartLeft}
                  y1={yBaseline}
                  x2={chartRight}
                  y2={yBaseline}
                  className="completion-time-baseline"
                />

                {/* Data line */}
                <polyline fill="none" stroke={typeSeries.color} strokeWidth="1.2" points={polylinePoints} />

                {/* Data points with annotations */}
                {points.map((point, index) => (
                  <g key={index}>
                    <circle cx={point.x} cy={point.y} r="1" fill={typeSeries.color} />
                    {point.value > 0 && (
                      <text x={point.x} y={point.y - 2} className="completion-time-annotation">
                        {formatDurationShort(point.value)}
                      </text>
                    )}
                  </g>
                ))}
              </g>
            );
          })}
        </svg>

        {/* X-axis labels (dates) below the chart */}
        <div className="completion-time-x-axis">
          {labels.map((label, index) => (
            <span key={label} className={`completion-time-x-label ct-x-label-${index}`}>
              {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
