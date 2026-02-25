import { useState, useCallback } from "react";

interface DataPoint {
  label: string;
  value: number;
}

interface MiniLineChartProps {
  data: DataPoint[];
  height?: number;
  color?: string;
  formatValue?: (v: number) => string;
}

export function MiniLineChart({
  data,
  height = 120,
  color = "var(--forge-accent)",
  formatValue = (v) => v.toFixed(1),
}: MiniLineChartProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const width = 300;
  const padding = { top: 16, right: 12, bottom: 24, left: 12 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs"
        style={{ height, color: "var(--forge-text-muted)" }}
      >
        No data yet
      </div>
    );
  }

  const values = data.map((d) => d.value);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;
  const padded = range * 0.1;

  const yMin = minVal - padded;
  const yMax = maxVal + padded;
  const yRange = yMax - yMin;

  const toX = (i: number) =>
    padding.left + (data.length === 1 ? chartW / 2 : (i / (data.length - 1)) * chartW);
  const toY = (v: number) =>
    padding.top + chartH - ((v - yMin) / yRange) * chartH;

  const points = data.map((d, i) => `${toX(i)},${toY(d.value)}`).join(" ");

  // Gradient polygon (fill area under line)
  const polygonPoints = [
    `${toX(0)},${toY(data[0].value)}`,
    ...data.map((d, i) => `${toX(i)},${toY(d.value)}`),
    `${toX(data.length - 1)},${padding.top + chartH}`,
    `${toX(0)},${padding.top + chartH}`,
  ].join(" ");

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const relX = x - padding.left;
      if (relX < 0 || relX > chartW || data.length <= 1) {
        setHoveredIndex(null);
        return;
      }
      const idx = Math.round((relX / chartW) * (data.length - 1));
      setHoveredIndex(Math.max(0, Math.min(data.length - 1, idx)));
    },
    [data.length, chartW, padding.left]
  );

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      style={{ maxHeight: height }}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => setHoveredIndex(null)}
    >
      <defs>
        <linearGradient id="line-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.3} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </linearGradient>
      </defs>

      {/* Fill area */}
      <polygon points={polygonPoints} fill="url(#line-gradient)" />

      {/* Line */}
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />

      {/* Data points */}
      {data.map((d, i) => (
        <circle
          key={i}
          cx={toX(i)}
          cy={toY(d.value)}
          r={hoveredIndex === i ? 4 : 2.5}
          fill={color}
          stroke="var(--forge-bg)"
          strokeWidth={1.5}
        />
      ))}

      {/* X-axis labels (first & last) */}
      {data.length >= 2 && (
        <>
          <text
            x={padding.left}
            y={height - 4}
            fontSize={9}
            fill="var(--forge-text-muted)"
          >
            {data[0].label}
          </text>
          <text
            x={width - padding.right}
            y={height - 4}
            fontSize={9}
            fill="var(--forge-text-muted)"
            textAnchor="end"
          >
            {data[data.length - 1].label}
          </text>
        </>
      )}

      {/* Tooltip */}
      {hoveredIndex !== null && (
        <>
          {/* Vertical guide line */}
          <line
            x1={toX(hoveredIndex)}
            y1={padding.top}
            x2={toX(hoveredIndex)}
            y2={padding.top + chartH}
            stroke="var(--forge-border)"
            strokeWidth={1}
            strokeDasharray="3,3"
          />
          {/* Tooltip box */}
          <rect
            x={Math.min(toX(hoveredIndex) - 30, width - 72)}
            y={Math.max(toY(data[hoveredIndex].value) - 28, 0)}
            width={60}
            height={20}
            rx={4}
            fill="var(--forge-channel)"
            stroke="var(--forge-border)"
            strokeWidth={0.5}
          />
          <text
            x={Math.min(toX(hoveredIndex), width - 42)}
            y={Math.max(toY(data[hoveredIndex].value) - 14, 12)}
            fontSize={10}
            fill="var(--forge-text)"
            textAnchor="middle"
            fontFamily="monospace"
          >
            {formatValue(data[hoveredIndex].value)}
          </text>
        </>
      )}
    </svg>
  );
}
