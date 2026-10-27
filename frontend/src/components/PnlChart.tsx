"use client";

import { useEffect, useMemo, useRef } from "react";
import { BaselineSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { chartOptions } from "@/lib/chartTheme";
import { fmtSignedUsd, toneClass } from "@/lib/format";
import { snapshotsToPoints } from "@/lib/history";
import type { Snapshot } from "@/lib/types";
import { Panel } from "./Panel";

type Props = { snapshots: Snapshot[]; liveValue: number | null };

const LIVE_THROTTLE_S = 2;

/** Portfolio value over time; green above / red below the first snapshot. */
export function PnlChart({ snapshots, liveValue }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Baseline"> | null>(null);
  const lastTime = useRef(0);
  const points = useMemo(() => snapshotsToPoints(snapshots), [snapshots]);
  const base = points[0]?.value ?? null;

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      ...chartOptions(),
      timeScale: { ...chartOptions().timeScale, secondsVisible: false },
    });
    series.current = c.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: 10000 },
      topLineColor: "#26a69a",
      topFillColor1: "rgba(38, 166, 154, 0.25)",
      topFillColor2: "rgba(38, 166, 154, 0.02)",
      bottomLineColor: "#ef5350",
      bottomFillColor1: "rgba(239, 83, 80, 0.02)",
      bottomFillColor2: "rgba(239, 83, 80, 0.25)",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    if (base != null) s.applyOptions({ baseValue: { type: "price", price: base } });
    s.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    lastTime.current = points[points.length - 1]?.time ?? 0;
    if (points.length) chart.current?.timeScale().fitContent();
  }, [points, base]);

  // Append the live client-side total as a trailing point (throttled).
  useEffect(() => {
    const s = series.current;
    if (!s || liveValue == null || !points.length) return;
    const now = Math.floor(Date.now() / 1000);
    const lastSnap = points[points.length - 1].time;
    const hasLivePoint = lastTime.current > lastSnap;
    if (hasLivePoint && now - lastTime.current < LIVE_THROTTLE_S) {
      // Refresh the trailing live point in place.
      s.update({ time: lastTime.current as UTCTimestamp, value: liveValue });
      return;
    }
    if (now <= lastTime.current) return;
    s.update({ time: now as UTCTimestamp, value: liveValue });
    lastTime.current = now;
  }, [liveValue, points]);

  const change = liveValue != null && base != null ? liveValue - base : null;

  return (
    <Panel
      testId="pnl-chart"
      title="Portfolio value"
      right={
        change != null && (
          <span className={`num ${toneClass(change)}`}>{fmtSignedUsd(change)} since start</span>
        )
      }
      className="h-full"
    >
      <div ref={el} className="absolute inset-0" />
      {!points.length && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] text-faint">
          Waiting for data…
        </div>
      )}
    </Panel>
  );
}
