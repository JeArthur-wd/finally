"use client";

import { useState, type FormEvent } from "react";
import { fmtPct, fmtPrice, toneClass } from "@/lib/format";
import type { MarketStore } from "@/lib/marketStore";
import { changeVsOpen } from "@/lib/portfolio";
import type { PriceTick, WatchlistItem } from "@/lib/types";
import { Panel } from "./Panel";
import { Sparkline } from "./Sparkline";

type Props = {
  items: WatchlistItem[];
  store: MarketStore;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<string | null>;
  onRemove: (ticker: string) => void;
};

/** Price cell; remounts on every tick (keyed by timestamp) to replay the flash. */
function PriceCell({ ticker, tick, fallback }: { ticker: string; tick?: PriceTick; fallback: number | null }) {
  const flash =
    tick?.direction === "up" ? "animate-flash-up" : tick?.direction === "down" ? "animate-flash-down" : "";
  return (
    <span
      key={tick?.timestamp ?? "none"}
      data-testid={`watchlist-price-${ticker}`}
      className={`num rounded-[2px] px-1 py-px text-right text-[13px] font-medium text-text ${flash}`}
    >
      {fmtPrice(tick?.price ?? fallback)}
    </span>
  );
}

export function Watchlist({ items, store, selected, onSelect, onAdd, onRemove }: Props) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (!t) return;
    setBusy(true);
    const err = await onAdd(t);
    setBusy(false);
    setError(err);
    if (!err) setInput("");
  };

  return (
    <Panel
      title="Watchlist"
      right={<span className="num">{items.length}</span>}
      className="h-full"
      bodyClassName="flex flex-col"
    >
      <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 border-b border-border-soft px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
        <span>Symbol</span>
        <span className="text-right">Last</span>
        <span className="w-[58px] text-right">Chg</span>
      </div>
      <ul data-testid="watchlist" className="min-h-0 flex-1 overflow-y-auto">
        {items.map((item) => {
          const tick = store.prices[item.ticker];
          const price = tick?.price ?? item.price;
          const pct = changeVsOpen(price, store.openPrice(item.ticker) ?? item.open_price) ?? item.change_percent;
          const active = selected === item.ticker;
          return (
            <li
              key={item.ticker}
              data-testid={`watchlist-row-${item.ticker}`}
              onClick={() => onSelect(item.ticker)}
              className={`group relative flex cursor-pointer items-center gap-2 border-b border-border-soft/70 py-1.5 pl-3 pr-2 transition-colors hover:bg-panel-2 ${
                active ? "bg-panel-2 shadow-[inset_2px_0_0_#209dd7]" : ""
              }`}
            >
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <span className={`w-[52px] truncate text-[12.5px] font-semibold ${active ? "text-blue" : "text-text"}`}>
                  {item.ticker}
                </span>
                <Sparkline points={store.history[item.ticker]} />
              </div>
              <PriceCell ticker={item.ticker} tick={tick} fallback={item.price} />
              <span className={`num w-[58px] text-right text-[12px] ${toneClass(pct)}`}>{fmtPct(pct)}</span>
              <button
                type="button"
                data-testid={`watchlist-remove-${item.ticker}`}
                aria-label={`Remove ${item.ticker} from watchlist`}
                title="Remove"
                onClick={(e) => {
                  e.stopPropagation();
                  onRemove(item.ticker);
                }}
                className="flex h-5 w-5 items-center justify-center rounded-[2px] text-faint opacity-30 transition hover:bg-down/15 hover:text-down group-hover:opacity-100 focus-visible:opacity-100"
              >
                ×
              </button>
            </li>
          );
        })}
        {items.length === 0 && (
          <li className="px-3 py-6 text-center text-[12px] text-faint">Watchlist is empty — add a symbol below.</li>
        )}
      </ul>
      <form onSubmit={submit} className="shrink-0 border-t border-border-soft p-2">
        <div className="flex gap-1.5">
          <input
            data-testid="watchlist-add-input"
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            placeholder="Add symbol…"
            maxLength={6}
            spellCheck={false}
            autoComplete="off"
            className="num min-w-0 flex-1 rounded-[3px] border border-border bg-bg px-2 py-1.5 text-[12px] uppercase text-text placeholder:normal-case placeholder:text-faint focus:border-blue focus:outline-none"
          />
          <button
            type="submit"
            data-testid="watchlist-add-button"
            disabled={busy || !input.trim()}
            className="rounded-[3px] border border-blue/60 bg-blue/10 px-3 text-[12px] font-semibold text-blue transition hover:bg-blue/20 disabled:opacity-40"
          >
            Add
          </button>
        </div>
        {error && <p className="mt-1.5 text-[11px] text-down">{error}</p>}
      </form>
    </Panel>
  );
}
