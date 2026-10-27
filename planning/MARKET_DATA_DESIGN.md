# Market Data Backend — Implementation Design

This is the build document for FinAlly's market data subsystem. It gives the complete target code for `backend/app/market/`: the unified API, the GBM simulator and the Massive (Polygon.io) poller. It also covers the SSE stream, how the rest of the backend uses it, and the tests.

**How this document relates to the others**

| Doc | Role |
|---|---|
| `MARKET_DATA_SUMMARY.md` | What was built in the first pass (8 modules, 73 tests) |
| `MARKET_INTERFACE.md` / `MARKET_SIMULATOR.md` / `MASSIVE_API.md` | Research and review. They mark the changes the first pass still needs with 🔧 |
| **This doc** | **The single source of truth for implementation.** It merges the as-built code with every 🔧 change into finished code an agent can copy file by file |
| `archive/*` | Superseded first-pass designs. Do not implement from them |

Each file listing below is complete and starts with a `# backend/app/market/<file>.py` comment. Replace the existing file with it. Where a 🔧 change from the research docs is applied, a `CHANGE` note says which one.

*Verified against the installed `massive` SDK 2.2.0 (`backend/uv.lock`). The field names, exception types and `from_dict` keys used below come from its source.*

---

## Contents

1. [Architecture](#1-architecture)
2. [Decisions this design makes](#2-decisions-this-design-makes)
3. [File layout](#3-file-layout)
4. [Unified API](#4-unified-api)
   - 4.1 [`models.py` — `PriceUpdate`](#41-modelspy--priceupdate)
   - 4.2 [`tickers.py` — `normalize_ticker`](#42-tickerspy--normalize_ticker)
   - 4.3 [`cache.py` — `PriceCache`](#43-cachepy--pricecache)
   - 4.4 [`interface.py` — `MarketDataSource`](#44-interfacepy--marketdatasource)
   - 4.5 [`factory.py`](#45-factorypy)
   - 4.6 [`__init__.py`](#46-__init__py)
5. [Simulator](#5-simulator)
6. [Massive API source](#6-massive-api-source)
7. [SSE stream](#7-sse-stream)
8. [App-layer integration](#8-app-layer-integration)
9. [Frontend contract](#9-frontend-contract)
10. [Testing](#10-testing)
11. [Configuration](#11-configuration)
12. [Implementation order and acceptance checklist](#12-implementation-order-and-acceptance-checklist)

---

## 1. Architecture

```
                        create_market_data_source(cache)          (env-driven, once at startup)
                         │
             MASSIVE_API_KEY set? ──yes──►  MassiveDataSource   ── poll REST every N s ──► api.massive.com
                         └────────no──►  SimulatorDataSource  ── GBM step every 500 ms (in-process)
                                                   │
                                   one background task per process; the ONLY writer
                                                   ▼
                                     ┌───────────────────────────┐
                                     │ PriceCache                │  latest PriceUpdate per ticker
                                     │  + version counter        │  thread-safe, O(1) reads, no I/O
                                     └───────────────────────────┘
                     reads ▲               ▲                  ▲                 ▲
                           │               │                  │                 │
          GET /api/stream/prices   portfolio valuation   trade execution   LLM chat context
               (SSE, §7)            (GET /api/portfolio,  (fill price)      (§8.4)
                                     snapshots)

     App layer: TickerTracker (§8.2) decides WHICH tickers are tracked = watchlist ∪ open positions,
                and is the only code that calls source.add_ticker / remove_ticker.
```

Three rules hold the design together:

1. **Push, one writer.** A source writes into `PriceCache` from its own loop. Nobody asks a source for a price. A trade or an SSE tick never waits on the network.
2. **Strategy pattern.** `MarketDataSource` is an ABC. The two implementations are interchangeable, and nothing downstream checks which one is running (except `/api/health`, which reports `source.name`).
3. **The market layer doesn't know about business rules.** It prices whatever tickers it is given. The app layer decides which tickers those are, and validates symbols.

---

## 2. Decisions this design makes

These close the market-data items of PLAN §13. Other agents can rely on them.

| PLAN §13 item | Decision |
|---|---|
| 2 — SSE payload shape | One event = **dict of all tracked tickers**, sent when `cache.version` changes. See §7 and §9 |
| 3 — removing a held ticker | Tracked set = **watchlist ∪ open positions**, kept in sync by `TickerTracker` (§8.2) |
| 4 — trading an untracked ticker | The trade route adds it to the watchlist, syncs, then waits up to 3 s for a first price (§8.3) |
| 5 — ticker validation | `normalize_ticker()`: trim, uppercase, `^[A-Z]{1,5}(\.[A-Z]{1,2})?$`. Unknown symbols are accepted in simulator mode. In Massive mode they stay unpriced, and the trade path reports "no price available" |
| 6 — "daily change %" | `PriceUpdate.reference_price` + `session_change_percent`. Massive: previous close (true daily change). Simulator: seed price (change since the backend started) |
| 16 — sparse Massive ticks | Accepted. Events only fire when a price changes. The cache skips no-op writes so a closed market produces no events |
| 32 — watchlist cap | `MAX_TRACKED_TICKERS = 50`, enforced by the app layer (§8.2) |
| 33 — snapshot with missing prices | Valuation falls back to `avg_cost` for a held ticker with no price yet (§8.4) |

Also fixed here (bugs found in research):

- **Massive never priced anything.** `last_trade.timestamp` doesn't exist on the SDK model (`sip_timestamp`, in ns). Fixed with a plan-aware fallback chain (§6.1).
- **Free Massive keys got `NOT_AUTHORIZED` forever.** The source now switches automatically to end-of-day mode (§6.3).
- **Duplicate SSE routes.** The `APIRouter` was created at module level, so every factory call added routes to the same router. It is now created inside the factory (§7).
- **Swallowed cancellation in SSE.** `CancelledError` is no longer caught.
- **Removal race in Massive.** A poll that was in flight when a ticker was removed would put it back into the cache. Writes are now filtered against the current ticker set (§6.2).
- **The simulator wasn't reproducible.** It now uses an injected `numpy.random.Generator` (`SIMULATOR_SEED`), and gives unknown tickers a deterministic seed price.

---

## 3. File layout

```
backend/app/market/
├── __init__.py          public exports
├── models.py            PriceUpdate (frozen dataclass)                      CHANGED: reference_price
├── tickers.py           normalize_ticker, InvalidTickerError                NEW
├── cache.py             PriceCache                                          CHANGED: sticky ref, no-op skip
├── interface.py         MarketDataSource ABC                                CHANGED: name property
├── seed_prices.py       constants + seed_price_for()                        CHANGED: deterministic seeds
├── simulator.py         GBMSimulator (math) + SimulatorDataSource (asyncio) CHANGED: rng, dt, ref price
├── massive_client.py    extract_quote() + MassiveDataSource                 REWRITTEN
├── factory.py           create_market_data_source()                         CHANGED: env knobs
└── stream.py            create_stream_router()  → GET /api/stream/prices    CHANGED: router per call

backend/app/services/
└── ticker_tracker.py    TickerTracker, wait_for_price                       NEW (app layer)

backend/tests/market/
├── conftest.py          FakeMassiveClient, snapshot fixtures                NEW
├── test_models.py  test_cache.py  test_tickers.py
├── test_simulator.py  test_simulator_source.py
├── test_massive.py      real SDK models, no MagicMock snapshots             REWRITTEN
├── test_contract.py     one suite run against both sources                  NEW
├── test_factory.py  test_stream.py
```

No new dependencies: `numpy`, `massive`, `fastapi` are already in `pyproject.toml`.

---

## 4. Unified API

### 4.1 `models.py` — `PriceUpdate`

One immutable price observation. `previous_price` is the **previous tick** and drives the green/red flash. `reference_price` is the **session baseline** and drives the "daily change %" column.

```python
# backend/app/market/models.py
"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    # CHANGE (MARKET_INTERFACE §2.1): baseline for "daily change %".
    # Massive: previous session close. Simulator: seed price at session start.
    reference_price: float | None = None

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def session_change(self) -> float | None:
        """Absolute change from the reference price, or None if there is none."""
        if self.reference_price is None:
            return None
        return round(self.price - self.reference_price, 4)

    @property
    def session_change_percent(self) -> float | None:
        """Percentage change from the reference price ("daily change %")."""
        if not self.reference_price:
            return None
        return round((self.price - self.reference_price) / self.reference_price * 100, 4)

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "reference_price": self.reference_price,
            "session_change": self.session_change,
            "session_change_percent": self.session_change_percent,
        }
```

Example:

```python
>>> u = PriceUpdate("AAPL", price=191.20, previous_price=191.05, timestamp=1761562800.0,
...                 reference_price=190.00)
>>> u.direction, u.change, u.session_change_percent
('up', 0.15, 0.6316)
```

### 4.2 `tickers.py` — `normalize_ticker`

Ticker symbols are validated in one place, at the boundary: REST routes, the LLM action executor and DB seeding. After that, the sources and the cache assume clean input.

```python
# backend/app/market/tickers.py
"""Ticker symbol validation and normalisation (single source of truth)."""

from __future__ import annotations

import re

# 1-5 letters, optional share-class suffix: AAPL, V, BRK.B, BF.A
TICKER_RE = re.compile(r"[A-Z]{1,5}(?:\.[A-Z]{1,2})?")


class InvalidTickerError(ValueError):
    """Raised for a symbol that cannot be a US equity ticker."""


def normalize_ticker(raw: str) -> str:
    """Trim and uppercase `raw`; raise InvalidTickerError if it is not a valid symbol."""
    ticker = (raw or "").strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise InvalidTickerError(f"Invalid ticker symbol: {raw!r}")
    return ticker
```

```python
normalize_ticker(" aapl ")   # 'AAPL'
normalize_ticker("brk.b")    # 'BRK.B'
normalize_ticker("ZZZZZ")    # 'ZZZZZ'  (syntactically valid; whether it gets priced depends on the source)
normalize_ticker("AAPL1")    # InvalidTickerError
normalize_ticker("")         # InvalidTickerError
```

In a route, map the error to the PLAN's error shape: `except InvalidTickerError as e: raise HTTPException(400, detail={"error": str(e)})`.

### 4.3 `cache.py` — `PriceCache`

The one shared structure. A source writes to it. Everything else reads from it.

```python
# backend/app/market/cache.py
"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Bumped on every effective change (update or remove)

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        reference_price: float | None = None,
    ) -> PriceUpdate:
        """Record a new price for a ticker. Returns the current PriceUpdate.

        - First update for a ticker: previous_price == price (direction 'flat').
        - reference_price is sticky: None keeps the ticker's existing reference.
        - CHANGE (MARKET_INTERFACE §2.2): a write identical to the cached entry
          (same price, timestamp and reference) is a no-op and does NOT bump the
          version, so a closed market polled by Massive emits no SSE events.
        """
        price = round(price, 2)
        with self._lock:
            ts = timestamp if timestamp is not None else time.time()
            prev = self._prices.get(ticker)
            if reference_price is not None:
                ref = round(reference_price, 2)
            else:
                ref = prev.reference_price if prev else None

            if (
                prev is not None
                and prev.price == price
                and prev.timestamp == ts
                and prev.reference_price == ref
            ):
                return prev

            update = PriceUpdate(
                ticker=ticker,
                price=price,
                previous_price=prev.price if prev else price,
                timestamp=ts,
                reference_price=ref,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        """Remove a ticker. Bumps the version so SSE clients see it disappear."""
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1

    @property
    def version(self) -> int:
        """Current version counter. Useful for SSE change detection."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

Why a `threading.Lock` when everything runs on one event loop: the Massive fetch runs in a worker thread (`asyncio.to_thread`). Today it hands results back to the loop before writing, but the lock keeps the cache correct even if a future source writes from a thread. Each critical section is a few dict operations, so contention is negligible.

Behaviour at a glance:

```python
cache = PriceCache()
cache.update("AAPL", 190.0, timestamp=1.0, reference_price=190.0)   # v=1, flat, ref 190.0
cache.update("AAPL", 190.5, timestamp=2.0)                          # v=2, up,   ref still 190.0
cache.update("AAPL", 190.5, timestamp=2.0)                          # v=2  (no-op, not re-broadcast)
cache.update("AAPL", 190.5, timestamp=3.0)                          # v=3, flat (new observation)
cache.remove("AAPL")                                                 # v=4
cache.remove("AAPL")                                                 # v=4  (absent, no-op)
```

### 4.4 `interface.py` — `MarketDataSource`

```python
# backend/app/market/interface.py
"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source directly for prices —
    it reads from the cache. Tickers passed in are already normalised
    (see tickers.normalize_ticker).

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        await source.add_ticker("TSLA")
        await source.remove_ticker("GOOGL")
        await source.stop()
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for logs and /api/health:
        'simulator' | 'massive:snapshot' | 'massive:eod'."""

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Populates the cache before returning where possible, then starts a
        background task. Raises RuntimeError if called twice.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Idempotent. No cache writes afterwards."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and from the PriceCache.
        No-op if not present."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

The contract both implementations must honour. `test_contract.py` (§10.4) checks the shared rows.

| Behaviour | Simulator | Massive |
|---|---|---|
| Cache populated when `start()` returns | ✅ seed prices | ✅ first poll (may be empty on error, or for unknown symbols) |
| Price available right after `add_ticker()` | ✅ immediately | snapshot mode: ≈1 s (early poll); EOD mode: immediately, from cached bars |
| `remove_ticker()` | gone from cache at once | gone from cache at once; in-flight poll can't resurrect it |
| Unknown symbol | invents a deterministic price | never priced |
| Cadence | 500 ms | `MASSIVE_POLL_INTERVAL` (default 15 s); EOD mode ≥15 min |
| Errors in the loop | logged, loop continues | logged, loop continues |
| `start()` twice | `RuntimeError` | `RuntimeError` |
| `stop()` twice | no-op | no-op |

### 4.5 `factory.py`

```python
# backend/app/market/factory.py
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        logger.warning("Ignoring invalid %s=%r, using %s", name, raw, default)
        return default


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", name, raw)
        return None


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
        MASSIVE_POLL_INTERVAL  seconds between polls (default 15)
    - Otherwise → SimulatorDataSource (GBM simulation)
        SIMULATOR_SEED         integer seed for reproducible price paths (default: random)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        interval = max(1.0, _env_float("MASSIVE_POLL_INTERVAL", 15.0))
        logger.info("Market data source: Massive API (poll every %.1fs)", interval)
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)

    seed = _env_int("SIMULATOR_SEED")
    logger.info("Market data source: GBM Simulator (seed=%s)", seed)
    return SimulatorDataSource(price_cache=price_cache, seed=seed)
```

### 4.6 `__init__.py`

```python
# backend/app/market/__init__.py
"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate               - Immutable price snapshot dataclass
    PriceCache                - Thread-safe in-memory price store
    MarketDataSource          - Abstract interface for data providers
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router      - FastAPI router factory for SSE endpoint
    normalize_ticker          - Validate/normalise a ticker symbol
    InvalidTickerError        - Raised by normalize_ticker
"""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router
from .tickers import InvalidTickerError, normalize_ticker

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
    "normalize_ticker",
    "InvalidTickerError",
]
```

---

## 5. Simulator

The model (GBM, Cholesky-correlated shocks, random jumps) and its maths are described in `MARKET_SIMULATOR.md` §2. This section is the code.

### 5.1 `seed_prices.py`

The constants are unchanged. One function is added so unknown tickers start at the same price on every run.

```python
# backend/app/market/seed_prices.py
"""Seed prices and per-ticker parameters for the market simulator."""

from __future__ import annotations

import zlib

# Realistic starting prices for the default watchlist (as of project creation)
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
}

# Per-ticker GBM parameters
# sigma: annualized volatility (higher = more price movement)
# mu: annualized drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT": {"sigma": 0.20, "mu": 0.05},
    "AMZN": {"sigma": 0.28, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # High volatility
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "META": {"sigma": 0.30, "mu": 0.05},
    "JPM": {"sigma": 0.18, "mu": 0.04},  # Low volatility (bank)
    "V": {"sigma": 0.17, "mu": 0.04},  # Low volatility (payments)
    "NFLX": {"sigma": 0.35, "mu": 0.05},
}

# Default parameters for tickers not in the list above (dynamically added)
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Correlation groups for the simulator's Cholesky decomposition
# Tickers in the same group have higher intra-group correlation
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

# Correlation coefficients. Keep every intra-group value >= CROSS_GROUP_CORR and < 1
# so the correlation matrix stays positive-definite (MARKET_SIMULATOR §2.2).
INTRA_TECH_CORR = 0.6  # Tech stocks move together
INTRA_FINANCE_CORR = 0.5  # Finance stocks move together
CROSS_GROUP_CORR = 0.3  # Between sectors / unknown tickers
TSLA_CORR = 0.3  # TSLA does its own thing


def seed_price_for(ticker: str) -> float:
    """Starting price for a ticker: the table value, else a deterministic $50-$300.

    CHANGE (MARKET_SIMULATOR §2.4): crc32 instead of random.uniform, so e.g. PYPL
    starts at the same price after every restart and in every test.
    """
    if ticker in SEED_PRICES:
        return SEED_PRICES[ticker]
    return round(50.0 + (zlib.crc32(ticker.encode()) % 25_000) / 100, 2)
```

### 5.2 `simulator.py`

There are two classes. `GBMSimulator` is the pure maths: synchronous, steppable, with no asyncio and no cache. `SimulatorDataSource` is the asyncio adapter that owns timing and the cache writes.

```python
# backend/app/market/simulator.py
"""GBM-based market simulator."""

from __future__ import annotations

import asyncio
import logging
import math

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    TICKER_PARAMS,
    TSLA_CORR,
    seed_price_for,
)

logger = logging.getLogger(__name__)

# 252 trading days * 6.5 hours/day * 3600 seconds/hour
TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Math:
        S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)

    Where:
        S(t)   = current price
        mu     = annualized drift (expected return)
        sigma  = annualized volatility
        dt     = time step as fraction of a trading year
        Z      = correlated standard normal random variable (Z = L @ z, C = L L^T)

    Internal prices keep full precision; only reported prices are rounded.
    """

    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8 (500 ms tick)

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
        rng: np.random.Generator | None = None,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        # CHANGE (MARKET_SIMULATOR §7): injected generator → reproducible runs
        self._rng = rng if rng is not None else np.random.default_rng()

        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._seeds: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    # --- Public API ---

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        Hot path — called every 500ms. Keep it fast.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        z = self._rng.standard_normal(n)
        if self._cholesky is not None:
            z = self._cholesky @ z

        # One uniform draw per ticker decides whether a jump happens this tick
        jumps = self._rng.random(n) < self._event_prob
        sqrt_dt = math.sqrt(self._dt)

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            mu = self._params[ticker]["mu"]
            sigma = self._params[ticker]["sigma"]
            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * sqrt_dt * z[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            if jumps[i]:
                magnitude = self._rng.uniform(0.02, 0.05)
                sign = 1 if self._rng.random() < 0.5 else -1
                self._prices[ticker] *= 1 + sign * magnitude
                logger.debug(
                    "Random event on %s: %+.1f%%", ticker, sign * magnitude * 100
                )

            result[ticker] = round(self._prices[ticker], 2)
        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the simulation. Rebuilds the correlation matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the simulation. Rebuilds the correlation matrix."""
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._seeds[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        """Current (unrounded) price for a ticker, or None if not tracked."""
        return self._prices.get(ticker)

    def get_seed_price(self, ticker: str) -> float | None:
        """Price the ticker started this session at (its reference price)."""
        return self._seeds.get(ticker)

    def get_tickers(self) -> list[str]:
        """Return the list of currently tracked tickers."""
        return list(self._tickers)

    # --- Internals ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add a ticker without rebuilding Cholesky (for batch initialization)."""
        if ticker in self._prices:
            return
        seed = seed_price_for(ticker)
        self._tickers.append(ticker)
        self._prices[ticker] = seed
        self._seeds[ticker] = seed
        self._params[ticker] = dict(TICKER_PARAMS.get(ticker, DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky factor of the ticker correlation matrix.

        O(n^2) build + O(n^3) factorisation; microseconds for n <= 50.
        """
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Sector-based correlation between two tickers.

          - Either is TSLA:  0.3 (it does its own thing)
          - Both tech:       0.6
          - Both finance:    0.5
          - Anything else:   0.3
        """
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR


class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by the GBM simulator.

    Runs a background asyncio task that calls GBMSimulator.step() every
    `update_interval` seconds and writes results to the PriceCache.
    All mutation happens on the event loop thread, so no locking is needed here.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
        seed: int | None = None,
        time_scale: float = 1.0,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._seed = seed
        # CHANGE (MARKET_SIMULATOR §6): dt follows the tick interval, so changing the
        # interval does not change volatility per wall-clock second. time_scale > 1
        # is a "demo speed" knob (more movement per tick, same sigma).
        self._dt = update_interval * time_scale / TRADING_SECONDS_PER_YEAR
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "simulator"

    async def start(self, tickers: list[str]) -> None:
        if self._sim is not None:
            raise RuntimeError("SimulatorDataSource already started")
        self._sim = GBMSimulator(
            tickers=list(dict.fromkeys(tickers)),
            dt=self._dt,
            event_probability=self._event_prob,
            rng=np.random.default_rng(self._seed),
        )
        # Seed the cache so SSE / trades have data immediately
        for ticker in self._sim.get_tickers():
            self._write_seed(ticker)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(self._sim.get_tickers()))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim is None or ticker in self._sim.get_tickers():
            return
        self._sim.add_ticker(ticker)
        self._write_seed(ticker)  # priced immediately
        logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim is not None:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    # --- Internal ---

    def _write_seed(self, ticker: str) -> None:
        seed = self._sim.get_seed_price(ticker)
        # CHANGE (MARKET_SIMULATOR §5): reference_price = seed → "change since session start"
        self._cache.update(ticker=ticker, price=seed, reference_price=seed)

    async def _run_loop(self) -> None:
        """Core loop: step the simulation, write to cache, sleep."""
        while True:
            try:
                for ticker, price in self._sim.step().items():
                    self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")  # never let the task die
            await asyncio.sleep(self._interval)
```

Usage:

```python
cache = PriceCache()
sim = SimulatorDataSource(cache, seed=42)
await sim.start(["AAPL", "MSFT", "TSLA"])
cache.get("AAPL").to_dict()
# {'ticker': 'AAPL', 'price': 190.0, 'previous_price': 190.0, ..., 'direction': 'flat',
#  'reference_price': 190.0, 'session_change': 0.0, 'session_change_percent': 0.0}
await sim.add_ticker("PYPL")          # cache.get_price("PYPL") is set right away (deterministic seed)
await asyncio.sleep(1.1)              # two ticks later, AAPL has moved a few cents
await sim.stop()
```

**Not in scope:** persisting simulated prices across restarts. After a restart every ticker starts again from its seed while `avg_cost` stays as it was, so unrealised P&L jumps. This is accepted for a demo (MARKET_SIMULATOR §5).

---

## 6. Massive API source

The background (plans, endpoints, timestamp units) is in `MASSIVE_API.md`. The design below covers every plan without any configuration:

| Plan | What the poller does | Price freshness | `name` |
|---|---|---|---|
| Developer+ | filtered snapshot, uses `last_trade` | 15-min delayed / real-time | `massive:snapshot` |
| Starter | filtered snapshot, no `last_trade` → minute bar close | 15-min delayed | `massive:snapshot` |
| Basic (free) | first snapshot call returns `NOT_AUTHORIZED` → **switches to EOD mode**: grouped daily bars | last session close | `massive:eod` |

### 6.1 Price extraction: `extract_quote`

This is a pure function, so it can be tested with real SDK models. It works through a fallback chain because the fields present depend on the plan and the time of day.

```python
def extract_quote(snap: TickerSnapshot) -> tuple[float, float, float | None] | None:
    """Return (price, unix_seconds, reference_price) from a snapshot, or None.

    Fallback chain (MASSIVE_API §4.3):
      last_trade.price  (Developer+; sip_timestamp is NANOseconds)
      min.close         (Starter: latest minute bar; min.timestamp is MILLIseconds)
      day.close         (today's running bar)
      prev_day.close    (pre-market / just after the 3:30 AM ET reset)
    reference_price = prev_day.close (the "daily change" baseline).
    """
```

Worked examples, using the JSON shapes from `MASSIVE_API.md` §4.1:

| Snapshot contains | Returns |
|---|---|
| `lastTrade {p: 120.47, t: 1605195918306274000}`, `prevDay {c: 119.49}` | `(120.47, 1605195918.306, 119.49)` |
| no `lastTrade`, `min {c: 120.4201, t: 1684428720000}`, `prevDay {c: 119.49}` | `(120.4201, 1684428720.0, 119.49)` |
| only `prevDay {c: 119.49}`, `updated: 1605195918306274000` | `(119.49, 1605195918.306, 119.49)` |
| nothing priced | `None` (skipped and logged) |

### 6.2 `massive_client.py`

```python
# backend/app/market/massive_client.py
"""Massive (formerly Polygon.io) REST poller for real market data."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import SnapshotMarketType, TickerSnapshot

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

Quote = tuple[float, float, float | None]  # (price, unix_seconds, reference_price)


def extract_quote(snap: TickerSnapshot) -> Quote | None:
    """Return (price, unix_seconds, reference_price) from a snapshot, or None.

    CHANGE (MASSIVE_API §8.1/§8.2): the first pass read last_trade.timestamp, which
    does not exist (it is sip_timestamp, in ns), so no ticker was ever priced; and
    last_trade is None on Starter plans. Fallback chain:
      last_trade.price -> min.close -> day.close -> prev_day.close
    """
    ref = snap.prev_day.close if snap.prev_day and snap.prev_day.close else None
    fallback_ts = snap.updated / 1e9 if snap.updated else time.time()

    lt = snap.last_trade
    if lt and lt.price:
        return lt.price, (lt.sip_timestamp / 1e9 if lt.sip_timestamp else fallback_ts), ref
    if snap.min and snap.min.close:
        return snap.min.close, (snap.min.timestamp / 1e3 if snap.min.timestamp else fallback_ts), ref
    if snap.day and snap.day.close:
        return snap.day.close, fallback_ts, ref
    if ref:
        return ref, fallback_ts, ref
    return None


def _us_market_today() -> date:
    """Today's date in US Eastern time (approximated as UTC-5; DST is irrelevant here)."""
    return (datetime.now(UTC) - timedelta(hours=5)).date()


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive REST API.

    snapshot mode: one GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=...
                   per poll for all tracked tickers (Starter plan and up).
    eod mode:      GET /v2/aggs/grouped/locale/us/market/stocks/{date} for the last
                   two sessions (free Basic plan). Entered automatically when the
                   snapshot endpoint answers NOT_AUTHORIZED.

    The SDK client is synchronous, so API calls run in a worker thread; cache
    writes always happen back on the event loop.
    """

    EOD_POLL_INTERVAL = 15 * 60.0  # closes change once a day; this just catches the rollover
    EOD_LOOKBACK_DAYS = 10  # calendar days searched for the last two sessions
    WAKE_COALESCE = 1.0  # seconds to batch several add_ticker calls into one early poll

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
        client: RESTClient | None = None,  # injectable for tests
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._client = client
        self._tickers: list[str] = []
        self._mode: Literal["snapshot", "eod"] = "snapshot"
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        # EOD mode state: the whole market's last two sessions, so newly added
        # tickers can be priced without another API call.
        self._eod_anchor: date | None = None
        self._eod_closes: dict[str, tuple[float, float]] = {}  # ticker -> (close, unix_s)
        self._eod_prev: dict[str, float] = {}  # ticker -> previous session close

    @property
    def name(self) -> str:
        return f"massive:{self._mode}"

    async def start(self, tickers: list[str]) -> None:
        if self._task is not None:
            raise RuntimeError("MassiveDataSource already started")
        if self._client is None:
            # SDK retries 429/5xx itself (urllib3 backoff); keep timeouts short
            self._client = RESTClient(
                api_key=self._api_key, connect_timeout=5.0, read_timeout=10.0, retries=2
            )
        self._tickers = list(dict.fromkeys(tickers))

        await self._poll_once()  # cache has data (or a logged reason why not) on return

        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, mode=%s, %.1fs interval",
            len(self._tickers), self._mode, self._interval,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        if ticker in self._tickers:
            return
        self._tickers.append(ticker)
        if self._mode == "eod":
            self._write_eod([ticker])  # from cached grouped bars: no API call
        else:
            self._wake.set()  # early poll (coalesced) so the new ticker is priced in ~1s
        logger.info("Massive: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Loop ---

    async def _poll_loop(self) -> None:
        """Poll every interval, or early when add_ticker() wakes us."""
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
                await asyncio.sleep(self.WAKE_COALESCE)
            except TimeoutError:
                pass
            self._wake.clear()
            await self._poll_once()

    async def _poll_once(self) -> None:
        """One poll cycle. Never raises: failures are logged and retried next cycle."""
        if not self._tickers or self._client is None:
            return
        try:
            if self._mode == "snapshot":
                snaps = await asyncio.to_thread(self._fetch_snapshots, list(self._tickers))
                self._write_snapshots(snaps)
            else:
                await self._refresh_eod()
        except BadResponse as e:
            if self._mode == "snapshot" and "NOT_AUTHORIZED" in str(e):
                # CHANGE (MASSIVE_API §8.3): free plan has no snapshots → EOD mode
                logger.warning(
                    "Massive plan has no snapshot access; switching to end-of-day mode "
                    "(prices = last session close). Upgrade to Starter for intraday data."
                )
                self._mode = "eod"
                self._interval = max(self._interval, self.EOD_POLL_INTERVAL)
                await self._poll_once()
            else:
                logger.error("Massive poll failed: %s", e)  # 401 bad key, 429 after retries, ...
        except Exception:
            logger.exception("Massive poll failed")

    # --- Snapshot mode ---

    def _fetch_snapshots(self, tickers: list[str]) -> list[TickerSnapshot]:
        """Blocking SDK call; runs in a worker thread."""
        return self._client.get_snapshot_all(SnapshotMarketType.STOCKS, tickers=tickers)

    def _write_snapshots(self, snaps: list[TickerSnapshot]) -> None:
        # Filter against the CURRENT set: a ticker removed while the request was
        # in flight must not be written back into the cache.
        tracked = set(self._tickers)
        written = 0
        for snap in snaps:
            if snap.ticker not in tracked:
                continue
            quote = extract_quote(snap)
            if quote is None:
                logger.warning("Massive: no usable price in snapshot for %s", snap.ticker)
                continue
            price, ts, ref = quote
            self._cache.update(snap.ticker, price, timestamp=ts, reference_price=ref)
            written += 1
        missing = tracked - {s.ticker for s in snaps}
        if missing:
            logger.debug("Massive: no snapshot for %s (unknown symbols?)", sorted(missing))
        logger.debug("Massive poll: updated %d/%d tickers", written, len(tracked))

    # --- EOD mode ---

    async def _refresh_eod(self) -> None:
        anchor = _us_market_today()
        if anchor != self._eod_anchor or not self._eod_closes:
            closes, prev = await asyncio.to_thread(self._fetch_eod, anchor)
            if closes:
                self._eod_anchor, self._eod_closes, self._eod_prev = anchor, closes, prev
        self._write_eod(self._tickers)

    def _fetch_eod(self, anchor: date) -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
        """Find the two most recent sessions with data, walking back from yesterday.

        Weekends are skipped without a call, so a normal poll costs 2 calls and a
        post-holiday one 3: well inside the free tier's 5 calls/min. Only runs when
        the date rolls over, not on every 15-minute poll.
        """
        sessions: list[list] = []
        day = anchor - timedelta(days=1)
        for _ in range(self.EOD_LOOKBACK_DAYS):
            if day.weekday() < 5:  # Mon-Fri
                try:
                    bars = self._client.get_grouped_daily_aggs(day.isoformat(), adjusted=True)
                except BadResponse as e:
                    logger.debug("Massive grouped daily %s unavailable: %s", day, e)
                    bars = []
                if bars:
                    sessions.append(bars)
                    if len(sessions) == 2:
                        break
            day -= timedelta(days=1)

        if not sessions:
            return {}, {}
        latest = {b.ticker: (b.close, b.timestamp / 1e3) for b in sessions[0] if b.close}
        prev = {b.ticker: b.close for b in sessions[1] if b.close} if len(sessions) > 1 else {}
        return latest, prev

    def _write_eod(self, tickers: list[str]) -> None:
        for t in tickers:
            if t in self._eod_closes:
                close, ts = self._eod_closes[t]
                self._cache.update(t, close, timestamp=ts, reference_price=self._eod_prev.get(t))
```

Notes:

- **One request per poll, whatever the watchlist size.** Keep the tracked set ≤ 50 (§8.2), well under URL-length limits.
- **No duplicate SSE events on a closed market.** `last_trade.sip_timestamp` doesn't change, so `cache.update` is a no-op and the version doesn't move. EOD bars never change during the day for the same reason.
- **`asyncio.Event()` in `__init__`** is safe on Python ≥ 3.10. Events bind to the running loop the first time they are used, not when they are created.
- **Error policy:** 401 (bad key) and other failures are logged on each poll, and the app keeps running with no prices for those tickers. The SDK already retries 429 and 5xx responses with backoff.

### 6.3 Request walk-through

```
start(["AAPL","MSFT","ZZZZZ"])
 └─ _poll_once()  →  GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,ZZZZZ
     ├─ 200 (Starter): [AAPL{min.c=231.12, prevDay.c=229.80}, MSFT{...}]   # ZZZZZ silently absent
     │     cache: AAPL 231.12 ref 229.80 (+0.57%), MSFT ...
     └─ 403 {"status":"NOT_AUTHORIZED",...} (Basic)
           → mode = eod, interval = 900 s
           → GET /v2/aggs/grouped/locale/us/market/stocks/2026-10-26   (Sunday → skipped, no call)
             GET .../2026-10-23 (Fri) → ~10k bars   ← latest
             GET .../2026-10-22 (Thu) → ~10k bars   ← prev (reference)
           cache: AAPL close(Fri) ref close(Thu), MSFT ...
add_ticker("PYPL")
 ├─ snapshot mode: wake loop → poll ~1 s later
 └─ eod mode: priced immediately from cached Fri/Thu bars (0 calls)
```

---

## 7. SSE stream

### 7.1 `stream.py`

```python
# backend/app/market/stream.py
"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)


def create_stream_router(
    price_cache: PriceCache,
    interval: float = 0.5,
    heartbeat: float = 15.0,
) -> APIRouter:
    """Create the SSE streaming router bound to a price cache.

    CHANGE (MARKET_INTERFACE §5): the APIRouter is created per call. It used to be
    module-level, so calling the factory twice registered duplicate routes.
    """
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """SSE endpoint for live price updates.

        Event format (one event holds ALL tracked tickers):
            data: {"AAPL": {"ticker": "AAPL", "price": 190.50, ...}, ...}
        """
        return StreamingResponse(
            _generate_events(price_cache, request, interval, heartbeat),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
    heartbeat: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames: a snapshot whenever the cache version changes, otherwise a
    comment heartbeat every `heartbeat` seconds so idle proxies keep the
    connection open (matters in Massive EOD mode, where prices rarely change).
    """
    yield "retry: 1000\n\n"  # browser reconnects 1 s after a drop

    last_version = -1
    last_sent = time.monotonic()
    client = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client)
    try:
        while not await request.is_disconnected():
            version = price_cache.version
            now = time.monotonic()
            if version != last_version:
                last_version = version
                data = {t: u.to_dict() for t, u in price_cache.get_all().items()}
                yield f"data: {json.dumps(data)}\n\n"
                last_sent = now
            elif now - last_sent >= heartbeat:
                yield ": ping\n\n"
                last_sent = now
            await asyncio.sleep(interval)
    finally:
        # CancelledError (server shutdown) propagates; we only log.
        logger.info("SSE client disconnected: %s", client)
```

### 7.2 Wire format

```
retry: 1000

data: {"AAPL":{"ticker":"AAPL","price":190.12,"previous_price":190.05,"timestamp":1761562800.1,"change":0.07,"change_percent":0.0368,"direction":"up","reference_price":190.0,"session_change":0.12,"session_change_percent":0.0632},"MSFT":{...}}

data: {"AAPL":{...},"MSFT":{...}}

: ping
```

- The first `data:` frame is sent on connect if the cache holds anything (version ≠ −1), so a new client is never blank.
- Each event is a **full snapshot**. A ticker missing from an event is no longer tracked.
- Size: about 300 B per ticker. 50 tickers × 2 events/s ≈ 30 KB/s per client, which is fine on localhost.
- **Never add `GZipMiddleware`.** It buffers the stream. Register this router **before** mounting `StaticFiles` at `/` (§8.1).

---

## 8. App-layer integration

This code lives outside `app/market/`. The backend API agent owns it, but the market-data contract depends on it, so it is specified here.

### 8.1 Lifespan wiring (`backend/app/main.py`)

```python
# backend/app/main.py  (market-data-relevant parts)
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.market import PriceCache, create_market_data_source, create_stream_router
from app.services.ticker_tracker import TickerTracker
from app import db  # init_db, watchlist_tickers, position_tickers (DB agent)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()                                   # create + seed if needed
    cache = PriceCache()
    source = create_market_data_source(cache)
    tracker = TickerTracker(source, wanted=lambda: db.watchlist_tickers() | db.position_tickers())
    await source.start(sorted(tracker.wanted()))   # watchlist ∪ positions
    app.state.price_cache = cache
    app.state.market = source
    app.state.tracker = tracker
    # ... start the 30 s portfolio snapshot task here (it reads app.state.price_cache)
    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(api_router)                     # /api/portfolio, /api/watchlist, /api/chat, ...


@app.get("/api/health")
async def health():
    return {"status": "ok", "market_data": app.state.market.name}

# the SSE router is included here too (see the note below), then:
app.mount("/", StaticFiles(directory="static", html=True), name="static")  # LAST
```

**Router/cache ordering.** `create_stream_router(cache)` needs the cache, but routes must exist before the static mount, which happens before the lifespan runs. So create the `PriceCache` at module level (it is cheap and inert), and use that same instance in both the router and the lifespan. Only the *source* is started inside the lifespan:

```python
price_cache = PriceCache()                          # module level

@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    source = create_market_data_source(price_cache) # same instance, not a new PriceCache()
    ...

app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(price_cache))
app.include_router(api_router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

Route handlers get what they need from `request.app.state`:

```python
def get_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_tracker(request: Request) -> TickerTracker:
    return request.app.state.tracker
```

### 8.2 `TickerTracker`: which tickers are live

```python
# backend/app/services/ticker_tracker.py
"""Keeps the market data source tracking exactly: watchlist ∪ open positions."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from app.market import MarketDataSource, PriceCache

MAX_TRACKED_TICKERS = 50  # PLAN §13 item 32; Cholesky rebuild + UI density


class TickerTracker:
    """The ONLY caller of source.add_ticker / remove_ticker.

    Call sync() after: watchlist add/remove, any trade that opens or closes a
    position, and chat actions. A lock serialises concurrent syncs so a sync
    computed from stale DB state can't remove a ticker another one just added.
    """

    def __init__(self, source: MarketDataSource, wanted: Callable[[], set[str]]) -> None:
        self._source = source
        self._wanted = wanted
        self._lock = asyncio.Lock()

    def wanted(self) -> set[str]:
        return set(self._wanted())

    async def sync(self) -> None:
        async with self._lock:
            wanted = self.wanted()
            current = set(self._source.get_tickers())
            for t in sorted(wanted - current):
                await self._source.add_ticker(t)
            for t in sorted(current - wanted):
                await self._source.remove_ticker(t)


async def wait_for_price(
    cache: PriceCache, ticker: str, timeout: float = 3.0, poll: float = 0.1
) -> float | None:
    """Wait until `ticker` has a cached price (Massive prices new tickers ~1 s later)."""
    deadline = time.monotonic() + timeout
    while (price := cache.get_price(ticker)) is None and time.monotonic() < deadline:
        await asyncio.sleep(poll)
    return price
```

Watchlist routes:

```python
@router.post("/api/watchlist", status_code=201)
async def add_to_watchlist(body: TickerIn, request: Request):
    try:
        ticker = normalize_ticker(body.ticker)
    except InvalidTickerError as e:
        raise HTTPException(400, detail={"error": str(e)})
    if ticker not in db.watchlist_tickers() and len(db.watchlist_tickers()) >= MAX_TRACKED_TICKERS:
        raise HTTPException(400, detail={"error": f"Watchlist is full ({MAX_TRACKED_TICKERS} tickers)"})
    db.add_watchlist(ticker)                     # idempotent: ON CONFLICT DO NOTHING
    await get_tracker(request).sync()
    update = get_cache(request).get(ticker)      # None in Massive mode for ~1 s, or forever if unknown
    return {"ticker": ticker, "price": update.to_dict() if update else None}


@router.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    ticker = normalize_ticker(ticker)
    if not db.remove_watchlist(ticker):
        raise HTTPException(404, detail={"error": f"{ticker} is not on the watchlist"})
    await get_tracker(request).sync()            # keeps tracking it if a position is open
    return {"ticker": ticker, "removed": True}
```

### 8.3 Trade execution: getting a fill price

```python
async def resolve_fill_price(ticker: str, request: Request) -> float:
    """Price for a market order; starts tracking the ticker if needed (PLAN §13 item 4)."""
    cache, tracker = get_cache(request), get_tracker(request)
    price = cache.get_price(ticker)
    if price is None:
        db.add_watchlist(ticker)                 # trading a ticker implies watching it
        await tracker.sync()
        price = await wait_for_price(cache, ticker, timeout=3.0)
    if price is None:
        raise TradeError(f"No price available for {ticker} yet. Check the symbol or try again shortly.")
    return price

# after a successful trade that created or closed a position:
await get_tracker(request).sync()
```

| Mode | Untracked valid ticker | Unknown symbol (`ZZZZZ`) |
|---|---|---|
| Simulator | filled instantly at its deterministic seed | filled (simulated market accepts anything) |
| Massive snapshot | filled after ~1 s | 400 "No price available" after 3 s |
| Massive EOD | filled instantly from cached bars | 400 immediately after the wait |

### 8.4 Other consumers

```python
cache: PriceCache = request.app.state.price_cache

# Portfolio valuation (GET /api/portfolio, 30 s snapshot task). PLAN §13 item 33:
# fall back to avg_cost for a held ticker that has no price yet.
def position_value(p) -> float:
    price = cache.get_price(p.ticker)
    return p.quantity * (price if price is not None else p.avg_cost)

total_value = cash + sum(position_value(p) for p in positions)

# Watchlist response: join DB order with live quotes
quotes = cache.get_all()
[{"ticker": t, **(quotes[t].to_dict() if t in quotes else {"price": None})} for t in db.watchlist_tickers()]

# LLM context: compact one line per ticker
"\n".join(f"{t}: ${u.price:.2f} ({u.session_change_percent or 0:+.2f}% today)" for t, u in quotes.items())
```

---

## 9. Frontend contract

TypeScript types that mirror `PriceUpdate.to_dict()`:

```ts
// frontend/src/lib/market.ts
export interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  timestamp: number;                    // Unix seconds
  change: number;
  change_percent: number;               // tick-to-tick
  direction: "up" | "down" | "flat";    // drives the green/red flash
  reference_price: number | null;
  session_change: number | null;
  session_change_percent: number | null; // the watchlist "daily change %" column
}
export type PriceSnapshot = Record<string, PriceUpdate>;

export function connectPrices(
  onSnapshot: (s: PriceSnapshot) => void,
  onStatus: (s: "connected" | "reconnecting" | "disconnected") => void,
): () => void {
  const es = new EventSource("/api/stream/prices");
  es.onopen = () => onStatus("connected");
  es.onmessage = (e) => onSnapshot(JSON.parse(e.data) as PriceSnapshot);
  es.onerror = () =>
    onStatus(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
  return () => es.close();
}
```

Client rules:

- **Flash only on a real tick.** Compare `timestamp` with the last value seen for that ticker. Each event resends every ticker, so an unchanged ticker must not flash again.
- **Sparkline and chart buffers:** append `(timestamp, price)` only when `timestamp` is new. Cap at 500 points per ticker (PLAN §13 item 18).
- `: ping` comments are invisible to `EventSource`. Nothing needs handling.
- `session_change_percent` may be `null`, e.g. Massive with no previous close. Render it as `—`.

---

## 10. Testing

Run with `uv run --extra dev pytest -v`. All tests are offline and deterministic: the simulator gets a seed, and Massive gets a fake client that returns **real SDK models**.

### 10.1 Fixtures (`tests/market/conftest.py`)

```python
# backend/tests/market/conftest.py
"""Shared fixtures for market data tests."""

import pytest
from massive.exceptions import BadResponse
from massive.rest.models import GroupedDailyAgg, TickerSnapshot

# JSON shapes from MASSIVE_API.md §4.1, one per plan / time-of-day case
SNAP_DEVELOPER = {  # has lastTrade (ns timestamps)
    "ticker": "AAPL", "updated": 1605195918306274000,
    "day": {"o": 119.62, "h": 120.53, "l": 118.81, "c": 120.4229, "v": 28727868},
    "prevDay": {"o": 117.19, "h": 119.63, "l": 116.44, "c": 119.49, "v": 110597265},
    "min": {"o": 120.435, "h": 120.468, "l": 120.37, "c": 120.4201, "t": 1684428720000},
    "lastTrade": {"p": 120.47, "s": 236, "x": 10, "t": 1605195918306274000},
}
SNAP_STARTER = {  # no lastTrade → minute bar (ms timestamp)
    "ticker": "MSFT", "updated": 1605195918306274000,
    "day": {"c": 410.10}, "prevDay": {"c": 405.00},
    "min": {"c": 410.25, "t": 1684428720000},
}
SNAP_PREMARKET = {  # only prevDay, right after the daily reset
    "ticker": "TSLA", "updated": 1605195918306274000, "prevDay": {"c": 250.00},
}
NOT_AUTHORIZED = BadResponse(
    '{"status":"NOT_AUTHORIZED","request_id":"x","message":"You are not entitled to this data."}'
)


class FakeMassiveClient:
    """Stands in for massive.RESTClient; returns real SDK model objects."""

    def __init__(self, snapshots=(), snapshot_error=None, grouped=None):
        self.snapshots = list(snapshots)
        self.snapshot_error = snapshot_error
        self.grouped = grouped or {}  # "YYYY-MM-DD" -> list of bar dicts
        self.calls: list[str] = []

    def get_snapshot_all(self, market_type, tickers=None):
        self.calls.append("snapshot")
        if self.snapshot_error:
            raise self.snapshot_error
        wanted = set(tickers or [])
        return [TickerSnapshot.from_dict(d) for d in self.snapshots if d["ticker"] in wanted]

    def get_grouped_daily_aggs(self, date, adjusted=None):
        self.calls.append(f"grouped:{date}")
        return [GroupedDailyAgg.from_dict(b) for b in self.grouped.get(str(date), [])]


@pytest.fixture
def fake_client():
    return FakeMassiveClient(snapshots=[SNAP_DEVELOPER, SNAP_STARTER, SNAP_PREMARKET])
```

### 10.2 Unified API tests

```python
# tests/market/test_cache.py (additions)
def test_reference_price_is_sticky():
    cache = PriceCache()
    cache.update("AAPL", 190.0, reference_price=190.0)
    u = cache.update("AAPL", 191.9)
    assert u.reference_price == 190.0
    assert u.session_change_percent == 1.0

def test_identical_write_does_not_bump_version():
    cache = PriceCache()
    cache.update("AAPL", 190.0, timestamp=1.0)
    v = cache.version
    cache.update("AAPL", 190.0, timestamp=1.0)
    assert cache.version == v
    cache.update("AAPL", 190.0, timestamp=2.0)
    assert cache.version == v + 1

def test_remove_bumps_version_only_if_present():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    v = cache.version
    cache.remove("AAPL")
    cache.remove("AAPL")
    assert cache.version == v + 1


# tests/market/test_tickers.py
@pytest.mark.parametrize("raw,expected", [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("V", "V")])
def test_normalize_valid(raw, expected):
    assert normalize_ticker(raw) == expected

@pytest.mark.parametrize("raw", ["", "  ", "AAPL1", "TOOLONG", "BRK.", ".B", "A-B", None])
def test_normalize_invalid(raw):
    with pytest.raises(InvalidTickerError):
        normalize_ticker(raw)
```

### 10.3 Simulator tests

```python
# tests/market/test_simulator.py (additions)
import numpy as np

def make_sim(tickers, seed=0, **kw):
    return GBMSimulator(tickers, rng=np.random.default_rng(seed), **kw)

def test_same_seed_same_path():
    a, b = make_sim(["AAPL", "MSFT"]), make_sim(["AAPL", "MSFT"])
    assert [a.step() for _ in range(100)] == [b.step() for _ in range(100)]

def test_prices_stay_positive_with_constant_jumps():
    sim = make_sim(["AAPL", "TSLA"], event_probability=1.0)
    for _ in range(2_000):
        assert all(p > 0 for p in sim.step().values())

def test_log_return_moments_and_correlation():
    sim = make_sim(["AAPL", "MSFT", "TSLA"], event_probability=0.0)
    n = 50_000
    prev = np.array([sim.get_price(t) for t in sim.get_tickers()])
    rets = np.empty((n, 3))
    for i in range(n):
        sim.step()
        cur = np.array([sim.get_price(t) for t in sim.get_tickers()])  # unrounded
        rets[i] = np.log(cur / prev)
        prev = cur
    dt = GBMSimulator.DEFAULT_DT
    assert rets[:, 0].std() == pytest.approx(0.22 * np.sqrt(dt), rel=0.03)
    corr = np.corrcoef(rets.T)
    assert corr[0, 1] == pytest.approx(0.6, abs=0.03)   # AAPL~MSFT (tech)
    assert corr[0, 2] == pytest.approx(0.3, abs=0.03)   # AAPL~TSLA

def test_cholesky_ok_for_50_mixed_tickers():
    tickers = list(SEED_PRICES) + [f"X{chr(65 + i)}" for i in range(40)]
    sim = make_sim(tickers)
    assert sim._cholesky.shape == (50, 50)

def test_unknown_ticker_seed_is_deterministic():
    assert seed_price_for("PYPL") == seed_price_for("PYPL")
    assert 50.0 <= seed_price_for("PYPL") <= 300.0


# tests/market/test_simulator_source.py (additions)
async def test_start_sets_reference_to_seed():
    cache = PriceCache()
    src = SimulatorDataSource(cache, seed=1)
    await src.start(["AAPL"])
    assert cache.get("AAPL").reference_price == 190.0
    await src.stop()

async def test_loop_survives_step_exception(monkeypatch):
    cache = PriceCache()
    src = SimulatorDataSource(cache, update_interval=0.01, seed=1)
    await src.start(["AAPL"])
    calls = {"n": 0}
    real_step = src._sim.step
    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_step()
    monkeypatch.setattr(src._sim, "step", flaky)
    await asyncio.sleep(0.05)
    assert calls["n"] > 1
    await src.stop()
```

### 10.4 Contract tests: one suite, both sources

```python
# backend/tests/market/test_contract.py
import pytest

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource

from .conftest import SNAP_DEVELOPER, SNAP_STARTER, FakeMassiveClient


def make_simulator(cache):
    return SimulatorDataSource(cache, update_interval=0.05, seed=7)


def make_massive(cache):
    client = FakeMassiveClient(snapshots=[SNAP_DEVELOPER, SNAP_STARTER])
    return MassiveDataSource("k", cache, poll_interval=60.0, client=client)


@pytest.fixture(params=[make_simulator, make_massive], ids=["simulator", "massive"])
async def source(request):
    cache = PriceCache()
    src = request.param(cache)
    await src.start(["AAPL", "MSFT"])
    yield src, cache
    await src.stop()


async def test_start_populates_cache(source):
    src, cache = source
    assert cache.get_price("AAPL") is not None and cache.get_price("MSFT") is not None
    assert sorted(src.get_tickers()) == ["AAPL", "MSFT"]


async def test_add_is_idempotent(source):
    src, _ = source
    await src.add_ticker("AAPL")
    assert src.get_tickers().count("AAPL") == 1


async def test_remove_clears_cache(source):
    src, cache = source
    await src.remove_ticker("MSFT")
    await src.remove_ticker("MSFT")           # no-op
    assert "MSFT" not in src.get_tickers() and "MSFT" not in cache


async def test_start_twice_raises(source):
    src, _ = source
    with pytest.raises(RuntimeError):
        await src.start(["AAPL"])


async def test_stop_is_idempotent(source):
    src, _ = source
    await src.stop()
    await src.stop()


async def test_has_name(source):
    src, _ = source
    assert src.name in {"simulator", "massive:snapshot", "massive:eod"}
```

### 10.5 Massive tests

```python
# backend/tests/market/test_massive.py
from datetime import date
from unittest.mock import patch

import pytest
from massive.rest.models import TickerSnapshot

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource, extract_quote

from .conftest import (
    NOT_AUTHORIZED,
    SNAP_DEVELOPER,
    SNAP_PREMARKET,
    SNAP_STARTER,
    FakeMassiveClient,
)


@pytest.mark.parametrize("raw,expected", [
    (SNAP_DEVELOPER, (120.47, 1605195918.306274, 119.49)),   # last trade, ns → s
    (SNAP_STARTER, (410.25, 1684428720.0, 405.00)),          # minute bar, ms → s
    (SNAP_PREMARKET, (250.00, 1605195918.306274, 250.00)),   # prevDay only
])
def test_extract_quote(raw, expected):
    price, ts, ref = extract_quote(TickerSnapshot.from_dict(raw))
    assert (price, ref) == (expected[0], expected[2])
    assert ts == pytest.approx(expected[1])


def test_extract_quote_unpriceable():
    assert extract_quote(TickerSnapshot.from_dict({"ticker": "ZZZZZ"})) is None


async def test_snapshot_poll_writes_cache_with_reference():
    cache = PriceCache()
    src = MassiveDataSource("k", cache, client=FakeMassiveClient([SNAP_DEVELOPER, SNAP_STARTER]))
    await src.start(["AAPL", "MSFT", "ZZZZZ"])
    assert cache.get_price("AAPL") == 120.47
    assert cache.get("MSFT").reference_price == 405.0
    assert "ZZZZZ" not in cache                     # unknown symbols stay unpriced
    assert src.name == "massive:snapshot"
    await src.stop()


async def test_repeat_poll_of_unchanged_market_does_not_bump_version():
    cache = PriceCache()
    src = MassiveDataSource("k", cache, client=FakeMassiveClient([SNAP_DEVELOPER]))
    await src.start(["AAPL"])
    v = cache.version
    await src._poll_once()
    assert cache.version == v
    await src.stop()


async def test_removed_ticker_not_resurrected_by_inflight_poll():
    cache = PriceCache()
    client = FakeMassiveClient([SNAP_DEVELOPER, SNAP_STARTER])
    src = MassiveDataSource("k", cache, client=client)
    await src.start(["AAPL", "MSFT"])
    snaps = client.get_snapshot_all("stocks", tickers=["AAPL", "MSFT"])  # "in flight"
    await src.remove_ticker("MSFT")
    src._write_snapshots(snaps)
    assert "MSFT" not in cache
    await src.stop()


GROUPED = {
    "2026-10-23": [{"T": "AAPL", "c": 231.10, "t": 1761249600000}, {"T": "PYPL", "c": 70.5, "t": 1761249600000}],
    "2026-10-22": [{"T": "AAPL", "c": 229.80, "t": 1761163200000}, {"T": "PYPL", "c": 69.0, "t": 1761163200000}],
}


async def test_not_authorized_switches_to_eod():
    cache = PriceCache()
    client = FakeMassiveClient(snapshot_error=NOT_AUTHORIZED, grouped=GROUPED)
    src = MassiveDataSource("k", cache, client=client)
    with patch("app.market.massive_client._us_market_today", return_value=date(2026, 10, 27)):  # Tue
        await src.start(["AAPL"])
        assert src.name == "massive:eod"
        assert cache.get_price("AAPL") == 231.10
        assert cache.get("AAPL").reference_price == 229.80
        # Mon 26 (empty), Fri 23, Thu 22; weekend not called
        assert client.calls == ["snapshot", "grouped:2026-10-26", "grouped:2026-10-23", "grouped:2026-10-22"]

        await src.add_ticker("PYPL")                 # served from cached bars, no new call
        assert cache.get_price("PYPL") == 70.5
        n = len(client.calls)
        await src._poll_once()                       # same day → no refetch
        assert len(client.calls) == n
    await src.stop()


async def test_other_errors_are_logged_not_raised(caplog):
    from massive.exceptions import BadResponse
    cache = PriceCache()
    src = MassiveDataSource("k", cache, client=FakeMassiveClient(snapshot_error=BadResponse("Unknown API Key")))
    await src.start(["AAPL"])                        # does not raise
    assert src.name == "massive:snapshot" and len(cache) == 0
    assert "Massive poll failed" in caplog.text
    await src.stop()
```

### 10.6 SSE and factory tests

```python
# backend/tests/market/test_stream.py
import json

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router


class FakeRequest:
    client = None
    def __init__(self, disconnect_after: int):
        self._n = disconnect_after
    async def is_disconnected(self):
        self._n -= 1
        return self._n < 0


async def test_emits_retry_then_full_snapshot():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("MSFT", 420.0)
    frames = [f async for f in _generate_events(cache, FakeRequest(1), interval=0)]
    assert frames[0] == "retry: 1000\n\n"
    data = json.loads(frames[1].removeprefix("data: "))
    assert set(data) == {"AAPL", "MSFT"} and data["AAPL"]["direction"] == "flat"


async def test_no_event_without_change_but_heartbeat():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    frames = [f async for f in _generate_events(cache, FakeRequest(3), interval=0, heartbeat=0)]
    assert sum(f.startswith("data:") for f in frames) == 1
    assert ": ping\n\n" in frames


def test_router_factory_does_not_share_routes():
    r1, r2 = create_stream_router(PriceCache()), create_stream_router(PriceCache())
    assert len(r1.routes) == len(r2.routes) == 1


# backend/tests/market/test_factory.py (additions)
def test_massive_poll_interval_env():
    with patch.dict(os.environ, {"MASSIVE_API_KEY": "k", "MASSIVE_POLL_INTERVAL": "5"}, clear=True):
        src = create_market_data_source(PriceCache())
    assert isinstance(src, MassiveDataSource) and src._interval == 5.0

def test_simulator_seed_env():
    with patch.dict(os.environ, {"SIMULATOR_SEED": "42"}, clear=True):
        src = create_market_data_source(PriceCache())
    assert isinstance(src, SimulatorDataSource) and src._seed == 42
```

**Existing tests that must change:** in `test_massive.py`, remove every `MagicMock` snapshot (they set the nonexistent `last_trade.timestamp`). `test_simulator.py` tests that patch the global `random` / `np.random` should pass `rng=` instead. `test_cache.py`'s `test_version_increments` still holds, because its writes differ.

---

## 11. Configuration

Add these to `.env.example`:

```bash
# Optional: Massive (Polygon.io) API key for real market data.
# Blank → built-in simulator (recommended). Free keys work but give end-of-day prices only.
MASSIVE_API_KEY=

# Optional: seconds between Massive polls (default 15; free keys auto-switch to 900)
MASSIVE_POLL_INTERVAL=

# Optional: integer seed for a reproducible simulator (E2E tests). Blank = random.
SIMULATOR_SEED=
```

| Knob | Where | Default | Notes |
|---|---|---|---|
| `MASSIVE_API_KEY` | env | — | selects the source |
| `MASSIVE_POLL_INTERVAL` | env | 15 s | min 1 s; Starter: ≥ 5, Advanced: 1–5 |
| `SIMULATOR_SEED` | env | random | set in `test/` compose for stable E2E runs |
| `update_interval` | `SimulatorDataSource(...)` | 0.5 s | `dt` follows it automatically |
| `time_scale` | `SimulatorDataSource(...)` | 1.0 | demo-speed volatility multiplier |
| `event_probability` | `SimulatorDataSource(...)` | 0.001 | 0 in statistical tests |
| SSE `interval` / `heartbeat` | `create_stream_router(...)` | 0.5 s / 15 s | |
| `MAX_TRACKED_TICKERS` | `ticker_tracker.py` | 50 | |

---

## 12. Implementation order and acceptance checklist

Implement in this order. Each step leaves the test suite green.

1. `models.py`, `tickers.py`, `cache.py` + their tests (§4.1–4.3, §10.2)
2. `interface.py` (`name`), `seed_prices.py`, `simulator.py` + tests (§4.4, §5, §10.3)
3. `massive_client.py`, `tests/market/conftest.py`, rewrite `test_massive.py` (§6, §10.1, §10.5)
4. `factory.py`, `__init__.py`, `stream.py` + tests (§4.5, §4.6, §7, §10.6)
5. `test_contract.py` (§10.4)
6. Update `backend/CLAUDE.md` (new `PriceCache.update` parameter, `name`, `normalize_ticker`, env vars) and `planning/MARKET_DATA_SUMMARY.md`
7. App layer, together with the API agent: `ticker_tracker.py`, lifespan, routes (§8)

Done when:

- [ ] `uv run --extra dev pytest` passes, and `uv run --extra dev ruff check app/ tests/` is clean
- [ ] No test uses `MagicMock` for a Massive snapshot
- [ ] `uv run market_data_demo.py` still runs (it uses only `PriceCache` + `SimulatorDataSource`)
- [ ] Two runs with `SIMULATOR_SEED=1` produce identical first 100 ticks
- [ ] `curl -N localhost:8000/api/stream/prices` shows `retry:`, then one `data:` frame with all 10 tickers including `session_change_percent`, then new frames about every 500 ms
- [ ] With a free Massive key: the logs show the switch to end-of-day mode once, `/api/health` reports `massive:eod`, and prices are the last session close
- [ ] Removing a watchlist ticker that is held keeps it in the SSE stream; removing one that isn't held drops it from the next frame
