/**
 * Dependency-free SVG line chart (no charting library needed).
 *
 * The cascade data has 41 points per series, so drawing polylines ourselves is
 * simpler and keeps the bundle small. A dashed line marks the random baseline.
 */
export default function LineChart({
  series,
  xLabel,
  yLabel,
  height = 360,
  yMin = 0,
  yMax = 100,
}) {
  const width = 780;
  const margin = { top: 18, right: 18, bottom: 48, left: 62 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const all = series.flatMap((item) => item.points);
  if (!all.length) {
    return <p className="empty">No cascade data available.</p>;
  }

  const xMax = Math.max(...all.map((point) => point.x), 1);
  const scaleX = (x) => margin.left + (x / xMax) * innerWidth;
  const scaleY = (y) =>
    margin.top + (1 - (y - yMin) / (yMax - yMin)) * innerHeight;

  const pathFor = (points) =>
    points
      .map(
        (point, index) =>
          `${index === 0 ? "M" : "L"}${scaleX(point.x).toFixed(1)},${scaleY(
            point.y,
          ).toFixed(1)}`,
      )
      .join(" ");

  const xTicks = Array.from({ length: 6 }, (_, index) => (xMax * index) / 5);
  const yTicks = Array.from(
    { length: 6 },
    (_, index) => yMin + ((yMax - yMin) * index) / 5,
  );

  return (
    <div className="chart">
      <div className="chart-legend">
        {series.map((item) => (
          <span key={item.name}>
            <span
              className="swatch"
              style={{
                background: item.color,
                opacity: item.dashed ? 0.65 : 1,
              }}
            />
            {item.name}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${yLabel} against ${xLabel}`}
      >
        <title>{`${yLabel} against ${xLabel}`}</title>

        {/* Horizontal grid and y-axis labels */}
        {yTicks.map((tick) => (
          <g key={`y-${tick}`}>
            <line
              x1={margin.left}
              x2={width - margin.right}
              y1={scaleY(tick)}
              y2={scaleY(tick)}
              stroke="#e2e8f0"
              strokeWidth="1"
            />
            <text
              x={margin.left - 10}
              y={scaleY(tick) + 4}
              textAnchor="end"
              fontSize="11"
              fill="#64748b"
            >
              {tick.toFixed(0)}%
            </text>
          </g>
        ))}

        {/* Vertical grid and x-axis labels */}
        {xTicks.map((tick) => (
          <g key={`x-${tick}`}>
            <line
              x1={scaleX(tick)}
              x2={scaleX(tick)}
              y1={margin.top}
              y2={height - margin.bottom}
              stroke="#f1f5f9"
              strokeWidth="1"
            />
            <text
              x={scaleX(tick)}
              y={height - margin.bottom + 18}
              textAnchor="middle"
              fontSize="11"
              fill="#64748b"
            >
              {tick.toFixed(1)}%
            </text>
          </g>
        ))}

        {/* Series */}
        {series.map((item) => (
          <path
            key={item.name}
            d={pathFor(item.points)}
            fill="none"
            stroke={item.color}
            strokeWidth={item.dashed ? 2 : 2.4}
            strokeDasharray={item.dashed ? "6 4" : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {/* Axis titles */}
        <text
          x={margin.left + innerWidth / 2}
          y={height - 6}
          textAnchor="middle"
          fontSize="12"
          fill="#475569"
        >
          {xLabel}
        </text>
        <text
          transform={`translate(14 ${margin.top + innerHeight / 2}) rotate(-90)`}
          textAnchor="middle"
          fontSize="12"
          fill="#475569"
        >
          {yLabel}
        </text>
      </svg>
    </div>
  );
}
