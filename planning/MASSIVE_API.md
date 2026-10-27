# Massive API (formerly Polygon.io): Stock Price Reference

Reference for retrieving **real-time / delayed** and **end-of-day** US stock prices for **multiple tickers** from Massive, written for the FinAlly backend.

*Researched 2026-10-27 against the Massive docs (`massive.com/docs`) and the source of the official Python SDK (`massive` on PyPI; versions 2.2.0, which is pinned in `backend/uv.lock`, and 2.9.1, the latest). Field names below are taken from the SDK source, not guessed.*

---

## 1. Background

- Polygon.io rebranded as **Massive** (announced 30 Oct 2025). Existing API keys keep working. The new base URL is `https://api.massive.com`, and `https://api.polygon.io` continues to work in parallel. Endpoint paths are unchanged.
- The official Python SDK is **`massive`** (`pip install massive` / `uv add massive`). It is the old `polygon-api-client` renamed, with the same `RESTClient` API, and it defaults to `api.massive.com`.
- The SDK reads the key from the **`MASSIVE_API_KEY`** environment variable by default. That is the same variable name FinAlly uses.

## 2. Plans: what matters for FinAlly

Market data access depends on the plan. **This is the most important constraint in this document.**

| Plan | Price/mo | Rate limit | Recency | Snapshots | Last trade | Aggregates / EOD |
|---|---|---|---|---|---|---|
| **Basic** (free) | $0 | **5 calls/min** | **End of day** | ❌ not included | ❌ | ✅ (2 yrs history) |
| Starter | $29 | Unlimited* | 15-min delayed | ✅ | ❌ (no trades) | ✅ (5 yrs) |
| Developer | $79 | Unlimited* | 15-min delayed | ✅ | ✅ | ✅ (10 yrs) |
| Advanced | $199 | Unlimited* | **Real-time** | ✅ | ✅ (+ quotes) | ✅ (all) |

\* "Unlimited" in practice means a soft limit. Massive recommends staying under ~100 requests/second.

Consequences:

1. **A free key cannot get intraday prices at all.** Snapshot endpoints return an authorization error (`NOT_AUTHORIZED`) on Basic. The only useful free endpoints are end-of-day: the grouped daily bars, previous close, and aggregates. PLAN.md §6 ("Free tier: poll every 15 seconds") assumes otherwise. With a free key, "live" prices will only change once per day.
2. **On Starter, snapshots have no `lastTrade` object.** That field is only returned "if your plan includes trades" (Developer and up). Code must fall back to the minute bar or day bar close (see §4.3).
3. Prices on Starter and Developer are 15 minutes delayed. That is fine for a simulated-money demo.

## 3. Authentication & conventions

```bash
# Either query string…
curl "https://api.massive.com/v2/aggs/ticker/AAPL/prev?apiKey=$MASSIVE_API_KEY"
# …or bearer header (what the Python SDK sends)
curl -H "Authorization: Bearer $MASSIVE_API_KEY" \
     "https://api.massive.com/v2/aggs/ticker/AAPL/prev"
```

- Tickers are **case-sensitive**: send `AAPL`, not `aapl`. Share classes use a dot, e.g. `BRK.B`.
- Responses carry `status` (`"OK"`, `"DELAYED"`, `"ERROR"`, `"NOT_AUTHORIZED"`) and a `request_id`.
- **Timestamp units are mixed. This is a common source of bugs:**
  - aggregate and bar `t` (`day`, `min`, `prevDay`, grouped daily, `/prev`, `/range`) is **Unix milliseconds**
  - trade and quote `t` (`lastTrade.t`, `lastQuote.t`) and snapshot `updated` are **Unix nanoseconds** (19 digits)
- Paginated endpoints return `next_url`. The SDK's `list_*` methods follow it automatically.
- Snapshot data is cleared daily around 3:30 AM ET and refills from 4:00 AM ET, when pre-market trading starts. Right after the reset, `day` may be empty, so fall back to `prevDay`.

### Python SDK client

```python
from massive import RESTClient

client = RESTClient()                          # reads MASSIVE_API_KEY
client = RESTClient(api_key="...",             # or explicit
                    connect_timeout=10.0,
                    read_timeout=10.0,
                    retries=3)                 # urllib3 retry on 413/429/499/5xx, backoff 0.1s×2^n
```

- The client is **synchronous** (urllib3). In asyncio code, call it via `asyncio.to_thread(...)`.
- It raises `massive.exceptions.BadResponse` on non-200 responses, with the JSON body as the message, and `AuthError` if no key is available at construction.
- It retries `429` automatically, up to `retries` times. After that you get `BadResponse`.

---

## 4. Real-time / delayed prices for multiple tickers

### 4.1 Full Market Snapshot, filtered (recommended): one call for N tickers

`GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,TSLA`

- Plans: Starter and up. 15-min delayed on Starter/Developer, real-time on Advanced and up.
- `tickers` is optional. Without it you get every ticker (~10k, several MB). **Always pass it.**
- Unknown symbols are **silently omitted**. Missing tickers do not cause an error.
- `include_otc=false` is the default.

Response (abridged from the docs):

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": 0.98,
      "todaysChangePerc": 0.82,
      "updated": 1605195918306274000,
      "day":     {"o": 119.62, "h": 120.53, "l": 118.81, "c": 120.4229, "v": 28727868, "vw": 119.725},
      "prevDay": {"o": 117.19, "h": 119.63, "l": 116.44, "c": 119.49,   "v": 110597265, "vw": 118.4998},
      "min":     {"o": 120.435, "h": 120.468, "l": 120.37, "c": 120.4201, "v": 270796, "av": 28724441,
                  "vw": 120.4129, "n": 762, "t": 1684428720000},
      "lastTrade": {"p": 120.47, "s": 236, "x": 10, "c": [14, 41], "i": "4046", "t": 1605195918306274000},
      "lastQuote": {"p": 120.46, "s": 8, "P": 120.47, "S": 4, "t": 1605195918507251700}
    }
  ]
}
```

SDK: `client.get_snapshot_all(market_type, tickers=None, include_otc=False)` → `list[TickerSnapshot]`

The `TickerSnapshot` fields, as defined in `massive/rest/models/snapshot.py`, and how they map to the JSON:

| SDK attribute | JSON | Type |
|---|---|---|
| `ticker` | `ticker` | `str` |
| `todays_change` | `todaysChange` | `float` ($ vs previous close) |
| `todays_change_percent` | `todaysChangePerc` | `float` (% vs previous close) |
| `updated` | `updated` | `int` (**ns**) |
| `day` / `prev_day` | `day` / `prevDay` | `Agg(open, high, low, close, volume, vwap, timestamp, …)` |
| `min` | `min` | `MinuteSnapshot(open, high, low, close, volume, accumulated_volume, timestamp(ms), …)` |
| `last_trade` | `lastTrade` | `LastTrade(price, size, exchange, conditions, sip_timestamp(ns), participant_timestamp(ns), …)` |
| `last_quote` | `lastQuote` | `LastQuote(bid_price, bid_size, ask_price, ask_size, sip_timestamp(ns), …)` |

> ⚠️ **`LastTrade` has no `timestamp` attribute.** The trade time is `last_trade.sip_timestamp`, in **nanoseconds**. Reading `last_trade.timestamp` raises `AttributeError` on a real response. Tests that use `MagicMock` snapshots will not catch this. See §8.

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient()
snaps = client.get_snapshot_all(
    SnapshotMarketType.STOCKS,          # or "stocks"
    tickers=["AAPL", "MSFT", "TSLA"],   # list is joined to "AAPL,MSFT,TSLA" by the SDK
)
for s in snaps:
    print(s.ticker, s.last_trade.price if s.last_trade else None, s.todays_change_percent)
```

### 4.2 Other intraday options (for completeness)

| Endpoint | SDK method | Plans | Use |
|---|---|---|---|
| `GET /v2/snapshot/locale/us/markets/stocks/tickers/{T}` | `get_snapshot_ticker("stocks", "AAPL")` | Starter+ | one ticker; same shape as above (under `ticker`) |
| `GET /v3/snapshot?ticker.any_of=AAPL,MSFT` | `list_universal_snapshots(ticker_any_of=[...], type="stocks")` | Starter+ | multi-asset; ≤250 tickers per call; returns per-ticker `error: "NOT_FOUND"` for bad symbols (useful for validation); `session.change_percent`, `last_trade`, `last_minute`, `market_status` |
| `GET /v2/last/trade/{T}` | `get_last_trade("AAPL")` → `LastTrade` | Developer+ | single ticker; 1 call per ticker, so it does not scale to a watchlist |
| `GET /v2/last/nbbo/{T}` | `get_last_quote("AAPL")` → `LastQuote` | Advanced+ | bid/ask |
| `GET /v2/snapshot/locale/us/markets/stocks/{gainers\|losers}` | `get_snapshot_direction("stocks", "gainers")` | Starter+ | top 20 movers (a nice extra for the AI context) |
| WebSocket `wss://socket.massive.com/stocks` (`delayed.massive.com` for 15-min) | `massive.WebSocketClient` | Starter+ | push stream; out of scope (PLAN chose REST polling) |

### 4.3 Extracting "the current price" robustly

The fields available depend on plan and time of day, so use a fallback chain:

```python
def snapshot_price(s) -> tuple[float, float] | None:
    """Return (price, unix_seconds) from a TickerSnapshot, or None if unpriceable."""
    if s.last_trade and s.last_trade.price:                       # Developer+ during/after session
        ts = s.last_trade.sip_timestamp or s.updated
        return s.last_trade.price, ts / 1e9                       # ns → s
    if s.min and s.min.close:                                     # Starter: latest minute bar
        return s.min.close, (s.min.timestamp or 0) / 1e3          # ms → s
    if s.day and s.day.close:                                     # today's running bar
        return s.day.close, (s.updated or 0) / 1e9
    if s.prev_day and s.prev_day.close:                           # pre-market / right after reset
        return s.prev_day.close, (s.updated or 0) / 1e9
    return None
```

Use `prev_day.close` as the reference price for "daily change %". `todays_change_percent` is that value already computed.

### 4.4 Raw `httpx` version (no SDK, async-native)

```python
import os, httpx

BASE = "https://api.massive.com"

async def fetch_snapshots(tickers: list[str]) -> list[dict]:
    async with httpx.AsyncClient(
        base_url=BASE,
        headers={"Authorization": f"Bearer {os.environ['MASSIVE_API_KEY']}"},
        timeout=10.0,
    ) as http:
        r = await http.get(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            params={"tickers": ",".join(tickers)},
        )
        if r.status_code == 429:
            raise RuntimeError("rate limited")
        r.raise_for_status()           # 401/403 → bad key or plan lacks snapshots
        return r.json().get("tickers", [])

# price = t.get("lastTrade", {}).get("p") or t.get("min", {}).get("c") or t["prevDay"]["c"]
```

---

## 5. End-of-day prices for multiple tickers

These endpoints work on **every plan, including free Basic**.

### 5.1 Grouped Daily (recommended for many tickers): one call for the whole market

`GET /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD}?adjusted=true`

Returns one OHLCV bar per US stock for that trading day. That is ~10k rows, so filter client-side. On Basic the latest available date is the last completed session. A weekend or holiday returns `resultsCount: 0`.

```json
{"status": "OK", "adjusted": true, "resultsCount": 1,
 "results": [{"T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97,
              "v": 131704427, "vw": 116.3058, "n": 4966, "t": 1605042000000}]}
```

SDK: `client.get_grouped_daily_aggs(date, adjusted=None, include_otc=False)` → `list[GroupedDailyAgg(ticker, open, high, low, close, volume, vwap, timestamp(ms), transactions)]`

```python
from datetime import date, timedelta
from massive import RESTClient

def eod_closes(client: RESTClient, tickers: set[str], lookback_days: int = 7) -> dict[str, float]:
    """Latest available close for each ticker, walking back over weekends/holidays."""
    day = date.today()
    for _ in range(lookback_days):
        bars = client.get_grouped_daily_aggs(day.isoformat(), adjusted=True)
        if bars:
            return {b.ticker: b.close for b in bars if b.ticker in tickers}
        day -= timedelta(days=1)
    return {}
```

On the free tier, budget **2 calls**: today, which may be empty, plus the previous date. Ideally anchor the date on `get_market_status()` or try yesterday first.

### 5.2 Previous Close: one call per ticker

`GET /v2/aggs/ticker/{T}/prev` → `client.get_previous_close_agg("AAPL")` → `list[PreviousCloseAgg]`. The result is a list with one element: `ticker, open, high, low, close, volume, vwap, timestamp(ms)`.

```python
prev = client.get_previous_close_agg("AAPL")[0]
print(prev.close)
```

At 5 calls/min this costs 2 minutes for a 10-ticker watchlist. Prefer grouped daily (§5.1).

### 5.3 Daily Open/Close for a specific date

`GET /v1/open-close/{T}/{date}` → `client.get_daily_open_close_agg("AAPL", "2026-10-23")` → `DailyOpenCloseAgg(open, high, low, close, pre_market, after_hours, volume, symbol, status)`. Use it when pre-market and after-hours prices are needed.

### 5.4 Historical bars (custom range)

`GET /v2/aggs/ticker/{T}/range/{multiplier}/{timespan}/{from}/{to}`, where `timespan` is one of `second|minute|hour|day|week|month|quarter|year` and `from`/`to` are `YYYY-MM-DD` or ms timestamps.

```python
# 30 daily bars (list_aggs paginates automatically; get_aggs returns one page)
bars = list(client.list_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-24", adjusted=True, sort="asc"))
closes = [(b.timestamp, b.close) for b in bars]

# Intraday 5-min bars for a chart seed (Basic: end-of-day only, i.e. up to yesterday)
bars = client.get_aggs("AAPL", 5, "minute", "2026-10-24", "2026-10-24", limit=5000)
```

This is useful as a future enhancement: seed the main chart with history instead of starting empty at page load (PLAN §13 item 18).

---

## 6. Supporting endpoints

| Need | Endpoint | SDK | Plans |
|---|---|---|---|
| Is the market open? | `GET /v1/marketstatus/now` → `{market: "open"\|"closed"\|"extended-hours", earlyHours, afterHours, serverTime, exchanges:{nyse,nasdaq}}` | `get_market_status()` | all |
| Validate a symbol / get company name | `GET /v3/reference/tickers/{T}` | `get_ticker_details("AAPL")` (`name`, `active`, `market`, `type`) | all |
| Search symbols | `GET /v3/reference/tickers?search=apple&market=stocks&active=true` | `list_tickers(search=..., market="stocks")` | all |

Polling only while `market == "open"`, with a slower cadence when it isn't, saves quota on metered plans.

---

## 7. Choosing a polling strategy

| Plan | Endpoint per poll | Calls per poll | Sensible interval | Price freshness |
|---|---|---|---|---|
| Basic (free) | Grouped daily (or `/prev` per ticker) | 1–2 | every 15–60 **minutes** (values change once/day) | previous session close |
| Starter / Developer | Filtered full-market snapshot | 1 | 5–15 s (data itself is 15-min delayed; minute bars on Starter change once/min) | 15-min delayed |
| Advanced+ | Filtered full-market snapshot | 1 | 1–5 s | real-time |

With one snapshot call per poll, the watchlist size does not affect the rate budget. Keep the `tickers` query under a few hundred symbols to stay clear of URL length limits. `/v3/snapshot` documents a hard 250-ticker cap.

## 8. Gotchas found during research (apply to `backend/app/market/massive_client.py`)

1. **`snap.last_trade.timestamp` does not exist.** Use `sip_timestamp`, which is in ns, so divide by `1e9`, not `1e3`. The current code catches the `AttributeError` and logs "Skipping snapshot", so **no ticker would ever be priced** against a real API. The unit tests pass only because they use `MagicMock`. Build test fixtures with `TickerSnapshot.from_dict({...})` using the JSON above so the real model is exercised.
2. **`last_trade` is `None` on Starter.** Implement the fallback chain in §4.3.
3. **Basic (free) keys get `NOT_AUTHORIZED` from snapshots.** Detect this on the first poll (`BadResponse` whose body contains `NOT_AUTHORIZED`) and switch to end-of-day mode (§5.1), with a clear log line, rather than logging an error every 15 s forever.
4. Unknown tickers are silently absent from snapshot results. A ticker added to the watchlist may never get a price, so the UI and the trade path must handle "no price yet".
5. Tickers are case-sensitive. Normalise with `.upper().strip()` before calling.
6. The SDK is blocking. Keep calling it via `asyncio.to_thread`. Its built-in retry with backoff covers transient 429/5xx.

## Sources

- Full Market Snapshot: https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot
- Single Ticker Snapshot: https://massive.com/docs/rest/stocks/snapshots/single-ticker-snapshot
- Unified Snapshot: https://massive.com/docs/rest/stocks/snapshots/unified-snapshot
- Daily Market Summary (grouped daily): https://massive.com/docs/rest/stocks/aggregates/daily-market-summary
- Previous Day Bar: https://massive.com/docs/rest/stocks/aggregates/previous-day-bar
- Custom Bars: https://massive.com/docs/rest/stocks/aggregates/custom-bars
- Last Trade: https://massive.com/docs/rest/stocks/trades-quotes/last-trade
- Market Status: https://massive.com/docs/rest/stocks/market-operations/market-status
- Quickstart / auth: https://massive.com/docs/rest/quickstart
- Pricing: https://massive.com/pricing
- Rebrand announcement: https://www.einpresswire.com/article/863823068/polygon-io-is-now-massive
- Python SDK: https://github.com/massive-com/client-python (PyPI `massive` 2.2.0 / 2.9.1 source inspected)
