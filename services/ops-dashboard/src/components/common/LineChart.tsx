import { useId, useMemo, useState } from "react";
import type { MouseEvent } from "react";

export interface LineChartSeries {
  name: string;
  colorVar: string;
  values: (number | null)[];
}

interface LineChartProps {
  title: string;
  xLabels: string[];
  series: LineChartSeries[];
  valueFormat?: (value: number) => string;
  height?: number;
}

const MARGIN = { top: 24, right: 16, bottom: 28, left: 16 };

function buildPath(
  values: (number | null)[],
  xFor: (i: number) => number,
  yFor: (v: number) => number,
): string {
  let d = "";
  let penDown = false;
  values.forEach((v, i) => {
    if (v === null) {
      penDown = false;
      return;
    }
    const cmd = penDown ? "L" : "M";
    d += `${cmd}${xFor(i)},${yFor(v)} `;
    penDown = true;
  });
  return d.trim();
}

/** Line/area chart with a legend (>=2 series), a shared crosshair, and a
 * hover tooltip — the dataviz skill's default interaction layer for this
 * mark. Nulls (future/unknown points) break the line rather than
 * interpolating through missing data. */
export function LineChart({
  title,
  xLabels,
  series,
  valueFormat = (v) => String(v),
  height = 240,
}: LineChartProps) {
  const titleId = useId();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const width = 600;
  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top - MARGIN.bottom;

  const maxValue = useMemo(() => {
    const all = series.flatMap((s) => s.values).filter((v): v is number => v !== null);
    return Math.max(...all, 1);
  }, [series]);

  const xFor = (i: number) =>
    MARGIN.left + (xLabels.length <= 1 ? 0 : (i / (xLabels.length - 1)) * plotWidth);
  const yFor = (v: number) => MARGIN.top + plotHeight - (v / maxValue) * plotHeight;

  function handleMove(event: MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = event.clientX - rect.left;
    const ratio = rect.width === 0 ? 0 : relativeX / rect.width;
    const index = Math.round(ratio * (xLabels.length - 1));
    setHoverIndex(Math.min(Math.max(index, 0), xLabels.length - 1));
  }

  return (
    <div>
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

        {series.map((s) => (
          <path
            key={s.name}
            d={buildPath(s.values, xFor, yFor)}
            fill="none"
            stroke={s.colorVar}
            strokeWidth={2}
            strokeLinecap="round"
          />
        ))}

        {hoverIndex !== null && (
          <line
            x1={xFor(hoverIndex)}
            x2={xFor(hoverIndex)}
            y1={MARGIN.top}
            y2={MARGIN.top + plotHeight}
            className="chart__crosshair"
          />
        )}
        {hoverIndex !== null &&
          series.map((s) => {
            const v = s.values[hoverIndex];
            if (v === null || v === undefined) return null;
            return (
              <circle key={s.name} cx={xFor(hoverIndex)} cy={yFor(v)} r={4} fill={s.colorVar} />
            );
          })}

        {xLabels.map(
          (label, i) =>
            (i === 0 || i === xLabels.length - 1 || i === Math.floor(xLabels.length / 2)) && (
              <text
                key={label}
                x={xFor(i)}
                y={MARGIN.top + plotHeight + 18}
                textAnchor="middle"
                className="chart__axis-label"
              >
                {label}
              </text>
            ),
        )}

        <rect
          x={MARGIN.left}
          y={MARGIN.top}
          width={plotWidth}
          height={plotHeight}
          fill="transparent"
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIndex(null)}
        />
      </svg>

      {hoverIndex !== null && (
        <div className="chart__tooltip" role="status">
          <strong>{xLabels[hoverIndex]}</strong>
          {series.map((s) => {
            const v = s.values[hoverIndex];
            return (
              <span key={s.name} className="chart__tooltip-row">
                <span
                  className="chart__legend-swatch"
                  style={{ background: s.colorVar }}
                  aria-hidden="true"
                />
                {s.name}: {v === null || v === undefined ? "—" : valueFormat(v)}
              </span>
            );
          })}
        </div>
      )}

      {series.length >= 2 && (
        <div className="chart__legend">
          {series.map((s) => (
            <span key={s.name} className="chart__legend-item">
              <span
                className="chart__legend-swatch"
                style={{ background: s.colorVar }}
                aria-hidden="true"
              />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
