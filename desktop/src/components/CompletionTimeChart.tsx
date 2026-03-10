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

  return (
    <div>
      <style>{tagStyleRules}</style>
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
        <svg viewBox={`0 0 100 ${visibleSeries.length * 30 + 10}`} preserveAspectRatio="none">
          {visibleSeries.map((typeSeries, typeIndex) => {
            const yOffset = typeIndex * 30 + 15;
            const points = typeSeries.values.map((value, index) => {
              const x = labels.length === 1 ? 50 : (index / (labels.length - 1)) * 100;
              const normalized = overallMax === 0 ? 0 : (value / overallMax) * 20;
              const y = yOffset - normalized;
              return `${x},${y}`;
            });

            return (
              <g key={typeSeries.type}>
                <polyline fill="none" stroke={typeSeries.color} strokeWidth="1.5" points={points.join(" ")} />
                {typeSeries.values.map((value, index) => (
                  <circle
                    key={index}
                    cx={labels.length === 1 ? 50 : (index / (labels.length - 1)) * 100}
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
    </div>
  );
}
