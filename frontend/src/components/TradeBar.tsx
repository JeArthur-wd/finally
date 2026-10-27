"use client";

import { useState, type FormEvent } from "react";
import type { Side } from "@/lib/types";

type Props = {
  ticker: string;
  onTickerChange: (t: string) => void;
  /** Resolves to null on success, or the user-facing error text. */
  onTrade: (ticker: string, quantity: number, side: Side) => Promise<{ error: string | null; message?: string }>;
};

/** Market-order entry: ticker, quantity, Buy / Sell. Instant fill, no confirm. */
export function TradeBar({ ticker, onTickerChange, onTrade }: Props) {
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState<Side | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async (side: Side) => {
    const t = ticker.trim().toUpperCase();
    const q = Number(qty);
    setOk(null);
    if (!t) return setError("Enter a ticker");
    if (!Number.isFinite(q) || q <= 0) return setError("Enter a quantity greater than 0");
    setBusy(side);
    const res = await onTrade(t, q, side);
    setBusy(null);
    setError(res.error);
    if (!res.error) setOk(res.message ?? null);
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit("buy");
  };

  const field =
    "num rounded-[3px] border border-border bg-bg px-2.5 py-1.5 text-[13px] text-text placeholder:text-faint focus:border-blue focus:outline-none";

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-wrap items-center gap-2 rounded-[3px] border border-border bg-panel px-3 py-2"
    >
      <span className="mr-1 text-[11px] font-semibold uppercase tracking-[0.09em] text-muted">Order</span>
      <input
        data-testid="trade-ticker"
        aria-label="Ticker"
        value={ticker}
        onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
        placeholder="TICKER"
        maxLength={6}
        spellCheck={false}
        autoComplete="off"
        className={`${field} w-24 font-semibold uppercase`}
      />
      <input
        data-testid="trade-quantity"
        aria-label="Quantity"
        type="number"
        inputMode="decimal"
        min="0"
        step="any"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        placeholder="Qty"
        className={`${field} w-24`}
      />
      <span className="text-[11px] text-faint">MKT</span>
      <button
        type="button"
        data-testid="trade-buy"
        disabled={busy !== null}
        onClick={() => void submit("buy")}
        className="rounded-[3px] bg-purple px-4 py-1.5 text-[12px] font-semibold text-white shadow-[inset_0_-2px_0_rgba(38,166,154,0.9)] transition hover:bg-purple-hi disabled:opacity-50"
      >
        {busy === "buy" ? "Buying…" : "Buy"}
      </button>
      <button
        type="button"
        data-testid="trade-sell"
        disabled={busy !== null}
        onClick={() => void submit("sell")}
        className="rounded-[3px] bg-purple px-4 py-1.5 text-[12px] font-semibold text-white shadow-[inset_0_-2px_0_rgba(239,83,80,0.9)] transition hover:bg-purple-hi disabled:opacity-50"
      >
        {busy === "sell" ? "Selling…" : "Sell"}
      </button>
      <div className="min-w-0 flex-1 text-[12px]" aria-live="polite">
        {error && (
          <span data-testid="trade-error" className="text-down">
            {error}
          </span>
        )}
        {!error && ok && (
          <span data-testid="trade-success" className="text-up">
            {ok}
          </span>
        )}
      </div>
    </form>
  );
}
