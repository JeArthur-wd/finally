"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { ConnectionTracker, type ConnectionStatus } from "@/lib/connection";
import type { MarketStore } from "@/lib/marketStore";
import { parsePriceMessage } from "@/lib/sse";

const STREAM_URL = "/api/stream/prices";
const MANUAL_RETRY_MS = 2000;

/**
 * Connect to the SSE price stream and feed `store`. EventSource retries on its
 * own while CONNECTING; if the browser gives up (CLOSED) we reconnect manually.
 */
export function usePriceStream(store: MarketStore): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>("reconnecting");

  useEffect(() => {
    const tracker = new ConnectionTracker();
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const refresh = () => setStatus(tracker.status(Date.now()));

    const connect = () => {
      if (disposed) return;
      es = new EventSource(STREAM_URL);
      es.onopen = () => {
        tracker.onOpen();
        refresh();
      };
      es.onmessage = (ev: MessageEvent<string>) => {
        const ticks = parsePriceMessage(ev.data);
        if (ticks) store.ingest(ticks);
      };
      es.onerror = () => {
        tracker.onError(Date.now());
        refresh();
        if (es && es.readyState === EventSource.CLOSED) {
          es.close();
          retry = setTimeout(connect, MANUAL_RETRY_MS);
        }
      };
    };

    connect();
    const ticker = setInterval(refresh, 1000);
    return () => {
      disposed = true;
      clearInterval(ticker);
      clearTimeout(retry);
      es?.close();
    };
  }, [store]);

  return status;
}

/** Re-render whenever the market store changes; returns its version. */
export function useMarketVersion(store: MarketStore): number {
  return useSyncExternalStore(store.subscribe, store.getVersion, store.getVersion);
}
