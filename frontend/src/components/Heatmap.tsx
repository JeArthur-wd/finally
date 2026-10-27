"use client";

import { useEffect, useRef, useState } from "react";
import { fmtPct, fmtUsd } from "@/lib/format";
import { weights } from "@/lib/portfolio";
import { pnlColor, squarify } from "@/lib/treemap";
import type { Position } from "@/lib/types";
import { Panel } from "./Panel";

type Props = { positions: Position[]; onSelect: (ticker: string) => void };

export const EMPTY_POSITIONS_TEXT = "No positions yet — buy something with the trade bar or ask FinAlly";

/** Treemap of positions: area = portfolio weight, colour = unrealized P&L %. */
export function Heatmap({ positions, onSelect }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: Math.floor(width), h: Math.floor(height) });
    });
    ro.observe(node);
    return () => ro.disconnect();
  }, []);

  const w = weights(positions);
  const byTicker = Object.fromEntries(positions.map((p) => [p.ticker, p]));
  const cells = squarify(
    positions.map((p) => ({ id: p.ticker, value: Math.max(p.market_value, 0) })),
    { x: 0, y: 0, w: size.w, h: size.h },
  );

  return (
    <Panel testId="heatmap" title="Portfolio heatmap" right={<span>±5% scale</span>} className="h-full">
      <div ref={box} className="absolute inset-1.5">
        {cells.map((c) => {
          const p = byTicker[c.id];
          const large = c.w > 70 && c.h > 46;
          const visible = c.w > 34 && c.h > 18;
          return (
            <button
              type="button"
              key={c.id}
              data-testid={`heatmap-cell-${c.id}`}
              data-pnl={p.unrealized_pnl_pct.toFixed(2)}
              onClick={() => onSelect(c.id)}
              title={`${c.id} · ${fmtUsd(p.market_value)} · ${fmtPct(p.unrealized_pnl_pct)}`}
              className="absolute flex flex-col items-center justify-center overflow-hidden border border-bg text-center transition-[background-color] duration-500 hover:brightness-125"
              style={{ left: c.x, top: c.y, width: c.w, height: c.h, backgroundColor: pnlColor(p.unrealized_pnl_pct) }}
            >
              {visible && (
                <span className={`font-bold text-white/95 ${large ? "text-[13px]" : "text-[10px]"}`}>{c.id}</span>
              )}
              {large && (
                <>
                  <span className="num text-[11px] text-white/90">{fmtPct(p.unrealized_pnl_pct)}</span>
                  <span className="num text-[10px] text-white/60">{(w[c.id] * 100).toFixed(1)}%</span>
                </>
              )}
            </button>
          );
        })}
      </div>
      {positions.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-[12px] text-faint">
          {EMPTY_POSITIONS_TEXT}
        </div>
      )}
    </Panel>
  );
}
