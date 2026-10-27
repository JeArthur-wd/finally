# Unified Market Data Interface

The single Python API that all FinAlly backend code uses to get stock prices. It is backed by **Massive** when `MASSIVE_API_KEY` is set, and by the **GBM simulator** otherwise. Downstream code (SSE, portfolio valuation, trade execution, LLM context) never knows which source is active.

Related docs: `MASSIVE_API.md` (provider research), `MARKET_SIMULATOR.md` (simulator design). The baseline code lives in `backend/app/market/`. This document describes that code as built and marks the **changes required** (🔧) that the Massive research turned up.

---

## 1. Design in one picture

```
              ┌─────────────── create_market_data_source(cache) ───────────────┐
              │  MASSIVE_API_KEY set? ──yes──► MassiveDataSource                │
              │                       └─no──► SimulatorDataSource              │
              └────────────────────────────────────────────────────────────────┘
                         │ (one background task, writes only)
                         ▼
                 ┌───────────────┐
                 │  PriceCache   │  latest PriceUpdate per ticker + version counter
                 └───────────────┘
            reads ▲      ▲        ▲
                  │      │        │
         SSE stream   portfolio   trade execution / chat context
```

Principles:

1. **Push model with one writer.** A source runs its own background loop and writes into `PriceCache`. Nobody asks the source for a price. Consumers read the cache, which is O(1) and never does I/O, so a trade or an SSE tick never waits on the network.
2. **Strategy pattern.** `MarketDataSource` is an ABC with two implementations, selected once at startup by a factory.
3. **The market layer is dumb about business rules.** It tracks whatever set of tickers it is told to. *Which* tickers (watchlist ∪ open positions) is decided by the app layer (§6).

## 2. Public API (`from app.market import …`)

| Symbol | Kind | Purpose |
|---|---|---|
| `PriceUpdate` | frozen dataclass | One price observation |
| `PriceCache` | class | Thread-safe latest-price store |
| `MarketDataSource` | ABC | Contract both sources implement |
| `create_market_data_source(cache)` | factory | Env-driven source selection |
| `create_stream_router(cache)` | factory | FastAPI router for `GET /api/stream/prices` |
| `normalize_ticker(raw)` 🔧 | function | Single place for ticker validation/normalisation |

### 2.1 `PriceUpdate`

```python
@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float                     # rounded to 2 dp
    previous_price: float            # price at the previous update (tick-to-tick)
    timestamp: float                 # Unix seconds (source time for Massive, wall clock for sim)
    reference_price: float | None = None   # 🔧 NEW: baseline for "daily change %"

    change: float            # property: price - previous_price
    change_percent: float    # property: tick-to-tick %
    direction: str           # property: "up" | "down" | "flat"  (drives the flash animation)
    session_change_percent: float | None   # 🔧 NEW property: (price - reference_price) / reference_price * 100

    def to_dict(self) -> dict: ...   # JSON-safe; includes all fields + properties
```

🔧 **Why `reference_price`:** PLAN §13 item 6 asks what "daily change %" means. The research gives a clean answer per source:

| Source | `reference_price` |
|---|---|
| Massive | `prev_day.close` from the snapshot. This is the real "daily change" and matches `todaysChangePerc`. |
| Simulator | The seed price when the ticker started being simulated (change since session start) |

Every client then shows the same number, computed on the server.

### 2.2 `PriceCache`

```python
class PriceCache:
    def update(self, ticker: str, price: float,
               timestamp: float | None = None,
               reference_price: float | None = None) -> PriceUpdate   # 🔧 reference_price param
    def get(self, ticker: str) -> PriceUpdate | None
    def get_price(self, ticker: str) -> float | None
    def get_all(self) -> dict[str, PriceUpdate]     # shallow copy, safe to iterate
    def remove(self, ticker: str) -> None
    @property
    def version(self) -> int                       # bumps on every update; SSE change detection
    def __contains__(self, ticker: str) -> bool
    def __len__(self) -> int
```

Rules:
- The first update for a ticker sets `previous_price = price`, giving direction `flat`.
- 🔧 `reference_price` is **sticky**: if the caller passes `None`, keep the previous value for that ticker. The simulator then only has to send it once, while Massive refreshes it every poll.
- 🔧 **Skip no-op writes for Massive.** If `price` and `timestamp` both equal the cached ones, don't bump `version`. Otherwise every 15 s poll on a closed market produces a "new" SSE event with `direction: flat`. The simulator always moves, so this does not affect it.
- Uses a `threading.Lock`, because the Massive fetch runs in a worker thread and only writes back to the event loop. That keeps it safe either way.

### 2.3 `MarketDataSource` (ABC)

```python
class MarketDataSource(ABC):
    async def start(self, tickers: list[str]) -> None     # once; seeds cache before returning if possible
    async def stop(self) -> None                          # idempotent; cancels the background task
    async def add_ticker(self, ticker: str) -> None       # no-op if present
    async def remove_ticker(self, ticker: str) -> None    # no-op if absent; also cache.remove(ticker)
    def get_tickers(self) -> list[str]
    @property
    def name(self) -> str        # 🔧 NEW: "simulator" | "massive:snapshot" | "massive:eod"  (for /api/health + logs)
```

Contract details that both implementations must honour, and that the tests should check for each:

| Behaviour | Simulator | Massive |
|---|---|---|
| Cache populated when `start()` returns | ✅ seed prices | ✅ immediate first poll (may be empty on error) |
| Price available right after `add_ticker()` | ✅ immediately | ❌ next poll (≤ interval); callers must tolerate `None` |
| Unknown symbol (e.g. `ZZZZZ`) | invents a price | never priced (silently absent from API) |
| Update cadence | 500 ms | `MASSIVE_POLL_INTERVAL` (default 15 s; EOD mode 15 min) |
| Failure handling | logs, keeps looping | logs, keeps looping; never raises out of the task |

### 2.4 Factory

```python
def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15"))   # 🔧 NEW env var
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)
    return SimulatorDataSource(price_cache=price_cache)
```

The source is returned **unstarted**. Add `MASSIVE_POLL_INTERVAL=` (blank = 15) to `.env.example`, next to `MASSIVE_API_KEY`.

### 2.5 `normalize_ticker` 🔧

```python
TICKER_RE = re.compile(r"^[A-Z][A-Z.]{0,5}$")   # AAPL, BRK.B, V

def normalize_ticker(raw: str) -> str:
    t = raw.strip().upper()
    if not TICKER_RE.fullmatch(t):
        raise ValueError(f"Invalid ticker symbol: {raw!r}")
    return t
```

Every entry point calls this once at the boundary: REST routes, the LLM action executor, and DB seeding. The sources may then assume normalised input. The current per-source `.upper().strip()` calls become redundant.

## 3. `MassiveDataSource`: required changes from research 🔧

The class structure stays as built: a poll loop, the sync SDK called via `asyncio.to_thread`, and one snapshot call per poll for all tickers. Three fixes are needed for it to work against the real API.

### 3.1 Fix price/timestamp extraction (blocking bug)

`snap.last_trade.timestamp` **does not exist** on the SDK's `LastTrade` model. The field is `sip_timestamp`, and it is in **nanoseconds**. As written, every snapshot raises `AttributeError`, which is caught and logged as "Skipping", so **no price is ever written**. On Starter plans `last_trade` is `None` anyway. Replace with a fallback chain:

```python
def _extract(snap) -> tuple[float, float, float | None] | None:
    """(price, unix_seconds, reference_price) or None."""
    ref = snap.prev_day.close if snap.prev_day and snap.prev_day.close else None
    lt = snap.last_trade
    if lt and lt.price:
        return lt.price, (lt.sip_timestamp or snap.updated) / 1e9, ref
    if snap.min and snap.min.close:
        return snap.min.close, snap.min.timestamp / 1e3, ref
    if snap.day and snap.day.close:
        return snap.day.close, (snap.updated or 0) / 1e9 or time.time(), ref
    if ref:
        return ref, (snap.updated or 0) / 1e9 or time.time(), ref
    return None
```

### 3.2 Handle the free (Basic) plan: auto-fallback to end-of-day mode

Snapshots are **not included** on the free plan. The API returns `NOT_AUTHORIZED`, so a free key would log an error every 15 seconds forever. Instead:

```python
class MassiveDataSource(MarketDataSource):
    EOD_INTERVAL = 15 * 60.0

    def __init__(self, api_key, price_cache, poll_interval=15.0):
        ...
        self._mode: Literal["snapshot", "eod"] = "snapshot"

    async def _poll_once(self) -> None:
        try:
            if self._mode == "snapshot":
                snaps = await asyncio.to_thread(self._fetch_snapshots)
                self._write_snapshots(snaps)
            else:
                closes = await asyncio.to_thread(self._fetch_eod_closes)   # grouped daily, 1–2 calls
                for t, (close, ts, prev_close) in closes.items():
                    self._cache.update(t, close, timestamp=ts, reference_price=prev_close)
        except BadResponse as e:
            if self._mode == "snapshot" and "NOT_AUTHORIZED" in str(e):
                logger.warning("Massive plan has no snapshot access → end-of-day mode "
                               "(prices update once per day). Upgrade to Starter for intraday.")
                self._mode, self._interval = "eod", self.EOD_INTERVAL
                await self._poll_once()
            else:
                logger.error("Massive poll failed: %s", e)
        except Exception as e:
            logger.error("Massive poll failed: %s", e)

    @property
    def name(self) -> str:
        return f"massive:{self._mode}"
```

`_fetch_eod_closes` uses `get_grouped_daily_aggs` for the most recent trading day that returns results, plus the day before it for `reference_price`. That is two calls for any number of tickers, which fits easily inside 5 calls/min (see `MASSIVE_API.md` §5.1).

### 3.3 Tests must use real SDK models

Replace `MagicMock` snapshots with `TickerSnapshot.from_dict({...})` built from the documented JSON (`MASSIVE_API.md` §4.1). Add one fixture per plan shape:
- Developer+: with `lastTrade`
- Starter: no `lastTrade`
- pre-market: only `prevDay`

Also add a test for the `NOT_AUTHORIZED` → EOD switch. This is what would have caught §3.1.

## 4. `SimulatorDataSource`

See `MARKET_SIMULATOR.md`. Interface-relevant points: it seeds the cache in `start()` and `add_ticker()` with `reference_price = seed price`, ticks every 500 ms, and `name == "simulator"`.

## 5. SSE stream (`create_stream_router`)

- `GET /api/stream/prices` emits `retry: 1000`, then, whenever `cache.version` changes (checked every 500 ms), **one event containing all tickers**:
  ```
  data: {"AAPL": {"ticker":"AAPL","price":190.12,"previous_price":190.05,"timestamp":1761562800.1,
                  "change":0.07,"change_percent":0.0368,"direction":"up",
                  "reference_price":190.0,"session_change_percent":0.0632}, "MSFT": {...}}
  ```
  PLAN §6's per-ticker event description is outdated. This dict-of-all-tickers shape is the contract the frontend parses.
- 🔧 Bug: `router = APIRouter(...)` is created at **module level** and the factory attaches routes to it. Calling the factory twice, as tests or app re-creation do, registers duplicate routes. Create the `APIRouter` **inside** `create_stream_router`.
- In Massive mode, events arrive only when a poll changes something: every few seconds on paid plans, about once a day on free. Sparklines will be sparse. This is accepted behaviour.
- Never add `GZipMiddleware`. It buffers the stream.

## 6. App-layer usage: which tickers are tracked

The tracked set must be **watchlist ∪ tickers with an open position** (PLAN §13 item 3a). Otherwise removing a held ticker from the watchlist drops its price, which breaks valuation and sells. The market layer doesn't know about the DB, so put a small reconciler in the app layer:

```python
# backend/app/services/tracking.py
async def sync_tracked_tickers(source: MarketDataSource, db) -> None:
    wanted = set(db.watchlist_tickers()) | set(db.position_tickers())
    current = set(source.get_tickers())
    for t in wanted - current:
        await source.add_ticker(t)
    for t in current - wanted:
        await source.remove_ticker(t)
```

Call it:
- after watchlist add/remove
- after any trade that opens or closes a position
- once at startup, by passing the union to `start()`

Route handlers and the chat executor **never** call `add_ticker`/`remove_ticker` directly.

### Lifespan wiring

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                           # create + seed if needed
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(sorted(watchlist_tickers() | position_tickers()))
    app.state.price_cache, app.state.market = cache, source
    app.include_router(create_stream_router(cache))     # before StaticFiles mount
    try:
        yield
    finally:
        await source.stop()
```

### Consumer recipes

```python
cache: PriceCache = request.app.state.price_cache

# Trade execution: fill at the cached price; reject if there is none yet
price = cache.get_price(ticker)
if price is None:
    raise HTTPException(400, {"error": f"No price available for {ticker} yet"})

# Portfolio valuation: fall back to avg_cost if a held ticker has no price yet (PLAN §13 item 33)
value = cash + sum(p.qty * (cache.get_price(p.ticker) or p.avg_cost) for p in positions)

# Watchlist response / LLM context
quotes = {t: u.to_dict() for t, u in cache.get_all().items()}
```

Trading an untracked ticker (PLAN §13 item 4): add it to the watchlist, `sync_tracked_tickers`, then retry. With the simulator the price exists immediately. With Massive the trade is rejected with "No price available yet, try again in a few seconds".

## 7. Testing the interface

- **Contract tests:** one parametrised suite run against both sources, with Massive's client stubbed to return real `TickerSnapshot` models. It checks `start` seeds the cache, `add`/`remove` semantics, that `remove` clears the cache, that `stop` is idempotent, and that `name` is set.
- **Downstream code:** use a `FakeSource(MarketDataSource)` that writes fixed prices on `start` and does nothing else. Never depend on the simulator's randomness in portfolio/API tests.
- **Determinism:** the simulator accepts a seed (see `MARKET_SIMULATOR.md` §7).

## 8. Change list (summary for the implementing agent)

| # | Change | File |
|---|---|---|
| 1 | Fix `last_trade.timestamp` → fallback chain with `sip_timestamp`/1e9 | `massive_client.py` |
| 2 | `NOT_AUTHORIZED` → EOD mode via grouped daily aggs | `massive_client.py` |
| 3 | Test fixtures via `TickerSnapshot.from_dict` | `tests/market/test_massive.py` |
| 4 | `reference_price` + `session_change_percent` | `models.py`, `cache.py`, both sources |
| 5 | Skip unchanged writes in cache (no version bump) | `cache.py` |
| 6 | `name` property on sources | `interface.py`, both sources |
| 7 | `MASSIVE_POLL_INTERVAL` env var | `factory.py`, `.env.example` |
| 8 | `normalize_ticker()` | new `market/tickers.py`, export from `__init__` |
| 9 | Create `APIRouter` inside the factory | `stream.py` |
| 10 | `sync_tracked_tickers` reconciler | app layer (new) |
