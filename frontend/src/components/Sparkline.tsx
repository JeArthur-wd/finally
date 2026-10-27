import type { Point } from "@/lib/marketStore";

type Props = { points: Point[] | undefined; width?: number; height?: number };

/** Build the SVG polyline `points` attribute for a series scaled into a box. */
export function sparkPath(values: number[], width: number, height: number, pad = 1.5): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  return values
    .map((v, i) => {
      const x = pad + i * step;
      const y = pad + (height - pad * 2) * (1 - (v - min) / span);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

/** Inline-SVG sparkline; colour follows direction since the first point. */
export function Sparkline({ points, width = 72, height = 22 }: Props) {
  const values = (points ?? []).slice(-120).map((p) => p.value);
  const path = sparkPath(values, width, height);
  const up = values.length > 1 && values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="block shrink-0" aria-hidden>
      {path ? (
        <polyline
          points={path}
          fill="none"
          stroke={up ? "#26a69a" : "#ef5350"}
          strokeWidth={1.25}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ) : (
        <line x1={2} x2={width - 2} y1={height / 2} y2={height / 2} stroke="#30363d" strokeDasharray="2 3" />
      )}
    </svg>
  );
}
