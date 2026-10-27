"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { chartOptions } from "@/lib/chartTheme";
import { fmtPct, fmtPrice, toneClass } from "@/lib/format";
import type { MarketStore } from "@/lib/marketStore";
import { changeVsOpen } from "@/lib/portfolio";
import { Panel } from "./Panel";

type Props = { ticker: string | null; store: MarketStore; version: number };

/** Large chart of buffered ticks for the selected ticker. */
export function MainChart({ ticker, store, version }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);
  const shown = useRef<{ ticker: string | null; count: number }>({ ticker: null, count: 0 });

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, chartOptions());
    series.current = c.addSeries(AreaSeries, {
      lineColor: "#209dd7",
      lineWidth: 2,
      topColor: "rgba(32, 157, 215, 0.28)",
      bottomColor: "rgba(32, 157, 215, 0.02)",
      priceLineColor: "#ecad0a",
      priceLineStyle: 2,
      lastValueVisible: true,
      crosshairMarkerBackgroundColor: "#209dd7",
    });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
      shown.current = { ticker: null, count: 0 };
    };
  }, []);

  useEffect(() => {
    const s = series.current;
    if (!s) return;
    const hist = ticker ? (store.history[ticker] ?? []) : [];
    const data = hist.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
    const prev = shown.current;
    if (prev.ticker !== ticker || data.length < prev.count || prev.count === 0) {
      s.setData(data);
      if (data.length) chart.current?.timeScale().fitContent();
    } else if (data.length) {
      s.update(data[data.length - 1]);
    }
    shown.current = { ticker, count: data.length };
  }, [ticker, store, version]);

  const tick = ticker ? store.prices[ticker] : undefined;
  const hist = ticker ? (store.history[ticker] ?? []) : [];
  const pct = ticker ? changeVsOpen(tick?.price, store.openPrice(ticker)) : null;
  const values = hist.map((p) => p.value);
  const hi = values.length ? Math.max(...values) : null;
  const lo = values.length ? Math.min(...values) : null;

  return (
    <Panel
      testId="main-chart"
      title={
        <span className="flex items-baseline gap-3 normal-case tracking-normal">
          <span className="text-[13px] font-bold text-text">{ticker ?? "—"}</span>
          <span className="num text-[13px] font-semibold text-text">{fmtPrice(tick?.price)}</span>
          <span className={`num text-[12px] ${toneClass(pct)}`}>{fmtPct(pct)}</span>
        </span>
      }
      right={
        <span className="num hidden gap-3 sm:flex">
          <span>
            O <span className="text-text">{fmtPrice(ticker ? store.openPrice(ticker) : null)}</span>
          </span>
          <span>
            H <span className="text-text">{fmtPrice(hi)}</span>
          </span>
          <span>
            L <span className="text-text">{fmtPrice(lo)}</span>
          </span>
        </span>
      }
      className="h-full"
    >
      <div ref={el} className="absolute inset-0" />
      {hist.length < 2 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[12px] text-faint">
          Waiting for data…
        </div>
      )}
    </Panel>
  );
}
