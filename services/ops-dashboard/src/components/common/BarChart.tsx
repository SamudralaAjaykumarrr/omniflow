import { useId, useState } from "react";

export interface BarChartDatum {
  label: string;
  value: number;
}

interface BarChartProps {
  title: string;
  data: BarChartDatum[];
  valueFormat?: (value: number) => string;
  colorVar?: string;
  height?: number;
}

const MARGIN = { top: 24, right: 12, bottom: 28, left: 12 };

function roundedTopRectPath(
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): string {
  const r = Math.min(radius, width / 2, Math.max(height, 0));
  if (height <= 0) return "";
  return `M${x},${y + height}
    L${x},${y + r}
    Q${x},${y} ${x + r},${y}
    L${x + width - r},${y}
    Q${x + width},${y} ${x + width},${y + r}
    L${x + width},${y + height}
    Z`;
}

/** Single-series vertical bar chart: thin gridlines, a rounded data-end
 * anchored to the baseline, a hover/focus-revealed direct value label
 * (dataviz skill's interaction rule — a bar chart ships a per-mark hover),
 * and one categorical color (never a rainbow for one series). */
export function BarChart({
  title,
  data,
  valueFormat = (v) => String(v),
  colorVar = "var(--series-1)",
  height = 220,
}: BarChartProps) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const titleId = useId();
  const width = 560;
  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top - MARGIN.bottom;
  const maxValue = Math.max(...data.map((d) => d.value), 1);
  const barGap = 10;
  const barWidth = data.length > 0 ? plotWidth / data.length - barGap : 0;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-labelledby={titleId}
      className="chart"
      preserveAspectRatio="xMidYMid meet"
    >
      <title id={titleId}>{title}</title>
      {[0.25, 0.5, 0.75, 1].map((fraction) => {
        const y = MARGIN.top + plotHeight * (1 - fraction);
        return (
          <line
            key={fraction}
            x1={MARGIN.left}
            x2={width - MARGIN.right}
            y1={y}
            y2={y}
            className="chart__gridline"
          />
        );
      })}
      <line
        x1={MARGIN.left}
        x2={width - MARGIN.right}
        y1={MARGIN.top + plotHeight}
        y2={MARGIN.top + plotHeight}
        className="chart__baseline"
      />
      {data.map((d, i) => {
        const barHeight = (d.value / maxValue) * plotHeight;
        const x = MARGIN.left + i * (barWidth + barGap) + barGap / 2;
        const y = MARGIN.top + plotHeight - barHeight;
        const isActive = activeIndex === i;
        return (
          <g
            key={d.label}
            tabIndex={0}
            role="img"
            aria-label={`${d.label}: ${valueFormat(d.value)}`}
            onMouseEnter={() => setActiveIndex(i)}
            onMouseLeave={() => setActiveIndex(null)}
            onFocus={() => setActiveIndex(i)}
            onBlur={() => setActiveIndex(null)}
            className="chart__bar-group"
          >
            <path
              d={roundedTopRectPath(x, y, Math.max(barWidth, 1), barHeight, 4)}
              fill={colorVar}
              opacity={isActive ? 1 : 0.85}
            />
            {isActive && (
              <text
                x={x + barWidth / 2}
                y={y - 6}
                textAnchor="middle"
                className="chart__value-label"
              >
                {valueFormat(d.value)}
              </text>
            )}
            <text
              x={x + barWidth / 2}
              y={MARGIN.top + plotHeight + 18}
              textAnchor="middle"
              className="chart__axis-label"
            >
              {d.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
