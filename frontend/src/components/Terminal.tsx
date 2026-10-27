"use client";

import { useCallback, useMemo, useState } from "react";
import { usePolling } from "@/hooks/usePolling";
import { useMarketVersion, usePriceStream } from "@/hooks/usePriceStream";
import { api, ApiError } from "@/lib/api";
import { fmtPrice, fmtQty } from "@/lib/format";
import { MarketStore } from "@/lib/marketStore";
import { computeLivePortfolio } from "@/lib/portfolio";
import type { Side } from "@/lib/types";
import { ChatPanel } from "./ChatPanel";
import { Header } from "./Header";
import { Heatmap } from "./Heatmap";
import { MainChart } from "./MainChart";
import { PnlChart } from "./PnlChart";
import { PositionsTable } from "./PositionsTable";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

const PORTFOLIO_POLL_MS = 15_000;
const WATCHLIST_POLL_MS = 30_000;
const HISTORY_POLL_MS = 30_000;

const msg = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

export default function Terminal() {
  const [store] = useState(() => new MarketStore());
  const status = usePriceStream(store);
  const version = useMarketVersion(store);

  const portfolio = usePolling(api.portfolio, PORTFOLIO_POLL_MS);
  const watchlist = usePolling(api.watchlist, WATCHLIST_POLL_MS);
  const history = usePolling(api.history, HISTORY_POLL_MS);

  const [picked, setPicked] = useState<string | null>(null);
  const [tradeTicker, setTradeTicker] = useState("");
  const [chatOpen, setChatOpen] = useState(true);

  const items = useMemo(() => watchlist.data ?? [], [watchlist.data]);
  const selected = picked ?? items[0]?.ticker ?? null;

  // Live valuation: recomputed on every SSE tick (version is the dependency).
  const live = useMemo(
    () => (portfolio.data ? computeLivePortfolio(portfolio.data, store.prices) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [portfolio.data, store, version],
  );

  const select = useCallback((t: string) => {
    setPicked(t);
    setTradeTicker(t);
  }, []);

  const refreshAll = useCallback(() => {
    void portfolio.refresh();
    void watchlist.refresh();
    void history.refresh();
  }, [portfolio, watchlist, history]);

  const onTrade = async (ticker: string, quantity: number, side: Side) => {
    try {
      const res = await api.trade(ticker, quantity, side);
      portfolio.setData(res.portfolio);
      void history.refresh();
      void watchlist.refresh();
      const t = res.trade;
      return {
        error: null,
        message: `${t.side === "buy" ? "Bought" : "Sold"} ${fmtQty(t.quantity)} ${t.ticker} @ ${fmtPrice(t.price)}`,
      };
    } catch (e) {
      return { error: msg(e) };
    }
  };

  const onAdd = async (ticker: string): Promise<string | null> => {
    try {
      await api.addTicker(ticker);
      await watchlist.refresh();
      return null;
    } catch (e) {
      return msg(e);
    }
  };

  const onRemove = async (ticker: string) => {
    // Optimistic removal; the refetch restores it if the server refused.
    watchlist.setData((cur) => (cur ? cur.filter((i) => i.ticker !== ticker) : cur));
    if (picked === ticker) setPicked(null);
    try {
      await api.removeTicker(ticker);
    } catch {
      /* fall through to refresh */
    }
    void watchlist.refresh();
  };

  const positions = live?.positions ?? [];

  return (
    <div className="flex h-screen min-h-[600px] flex-col overflow-hidden">
      <Header
        totalValue={live?.total_value ?? null}
        cash={live?.cash_balance ?? null}
        unrealizedPnl={live?.unrealized_pnl ?? null}
        positionsValue={live?.positions_value ?? null}
        status={status}
      />
      {(portfolio.error && !portfolio.data) && (
        <div className="shrink-0 border-b border-down/40 bg-down/10 px-4 py-1.5 text-[12px] text-down">
          Can&apos;t load portfolio: {portfolio.error}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <main className="grid min-w-0 flex-1 auto-rows-min gap-1.5 overflow-y-auto p-1.5 lg:grid-cols-[minmax(250px,300px)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden">
          <div className="h-[420px] min-h-0 lg:h-auto">
            <Watchlist
              items={items}
              store={store}
              selected={selected}
              onSelect={select}
              onAdd={onAdd}
              onRemove={onRemove}
            />
          </div>
          <div className="flex min-h-0 min-w-0 flex-col gap-1.5">
            <div className="h-[340px] min-h-[240px] lg:h-auto lg:flex-[1.25]">
              <MainChart ticker={selected} store={store} version={version} />
            </div>
            <TradeBar ticker={tradeTicker} onTickerChange={setTradeTicker} onTrade={onTrade} />
            <div className="grid min-h-0 gap-1.5 md:grid-cols-2 lg:flex-1">
              <div className="h-[260px] min-h-[180px] lg:h-auto">
                <Heatmap positions={positions} onSelect={select} />
              </div>
              <div className="h-[260px] min-h-[180px] lg:h-auto">
                <PnlChart snapshots={history.data ?? []} liveValue={live?.total_value ?? null} />
              </div>
            </div>
            <div className="h-[220px] min-h-[150px] shrink-0 lg:h-[30%]">
              <PositionsTable positions={positions} selected={selected} onSelect={select} />
            </div>
          </div>
        </main>
        <ChatPanel open={chatOpen} onToggle={() => setChatOpen((o) => !o)} onActions={refreshAll} />
      </div>
    </div>
  );
}
