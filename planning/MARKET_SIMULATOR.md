# Market Simulator: Approach & Code Structure

The default market data source, used whenever `MASSIVE_API_KEY` is unset. It produces believable, correlated, continuously moving stock prices with no network access or API key, entirely in-process. It implements the `MarketDataSource` contract in `MARKET_INTERFACE.md`.

Code: `backend/app/market/simulator.py` (math + data source) and `backend/app/market/seed_prices.py` (parameters). Items marked 🔧 are recommended changes; everything else describes the code as built.

---

## 1. Goals

| Goal | How |
|---|---|
| Looks like a real market | Geometric Brownian Motion: log-normal, always positive, percentage-scaled moves |
| Stocks move together | Sector correlation via Cholesky-decomposed correlation matrix |
| Visual drama for the demo | Rare random 2–5 % jumps |
| Recognisable prices | Realistic seed prices and per-ticker volatility |
| Smooth UI | 500 ms ticks, sub-cent to few-cent moves per tick |
| Zero friction | Pure Python + NumPy, no I/O, no external services |
| Testable | Pure, steppable math core separated from the asyncio loop |

Non-goals: order-book realism, intraday seasonality, mean reversion, market hours. The simulated market is always open.

## 2. The model

### 2.1 Geometric Brownian Motion

Each tick, every price is advanced with the exact GBM solution:

```
S(t+Δt) = S(t) · exp( (μ − σ²/2)·Δt  +  σ·√Δt·Z )
```

- `μ`: annualised drift (expected return), e.g. 0.05
- `σ`: annualised volatility, e.g. 0.22 for AAPL
- `Z`: standard normal draw, **correlated across tickers** (§2.2)
- `Δt`: the tick length as a fraction of a *trading* year:

```
TRADING_SECONDS_PER_YEAR = 252 days × 6.5 h × 3600 s = 5,896,800
Δt = 0.5 s / 5,896,800 ≈ 8.48e-8
```

Why the exact exponential form rather than `S·(1 + μΔt + σ√ΔtZ)`: it can never go negative, and it is unbiased at any Δt. The `−σ²/2` term is the Itô correction, so the *expected* price grows at `μ`.

**What this produces** (σ√Δt scaling, computed for the default parameters):

| Ticker (σ, seed) | per tick (500 ms) | per minute | per hour | per 6.5 h "day" |
|---|---|---|---|---|
| V (0.17, $280) | 0.005 % ≈ $0.014 | 0.05 % | 0.42 % | 1.1 % |
| AAPL (0.22, $190) | 0.006 % ≈ $0.012 | 0.07 % | 0.54 % | 1.4 % |
| NVDA (0.40, $800) | 0.012 % ≈ $0.09 | 0.13 % | 0.99 % | 2.5 % |
| TSLA (0.50, $250) | 0.015 % ≈ $0.04 | 0.16 % | 1.24 % | 3.2 % |

These are realistic daily ranges, and moves are large enough at 2 dp for most ticks to flash up or down. Low-σ, low-price tickers will show some `flat` ticks after rounding. Drift is invisible intraday (`μΔt ≈ 4e-9`), so the chart wanders rather than trends. That is intended.

### 2.2 Correlated moves (Cholesky)

Independent normals `z ~ N(0, I)` are turned into correlated ones by `Z = L·z`, where `L` is the lower-triangular Cholesky factor of the correlation matrix `C = L·Lᵀ`. Then `Cov(Z) = L·I·Lᵀ = C`.

Pairwise correlation rules (`seed_prices.py`):

| Pair | ρ |
|---|---|
| Both in tech (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX) | 0.6 |
| Both in finance (JPM, V) | 0.5 |
| Either is TSLA ("does its own thing") | 0.3 |
| Anything else: cross-sector, or a dynamically added unknown ticker | 0.3 |

**Cholesky is always safe here.** The matrix is positive-definite for any number of tickers, because it decomposes as

```
C = 0.3·𝟙𝟙ᵀ  +  0.3·t tᵀ  +  0.2·f fᵀ  +  D
```

where `t` and `f` are the indicator vectors of tech (excluding TSLA) and finance. The first three terms are PSD. The diagonal remainder `D` is 0.4 for tech, 0.5 for finance and 0.7 for others, so it is strictly positive. 🔧 Keep this property if you add sectors: give each new group a block term with intra-ρ ≥ the cross-ρ (0.3), and keep every intra-ρ < 1. Add a unit test that asserts `np.linalg.cholesky` succeeds for a 50-ticker mixed set.

The matrix is rebuilt on every add/remove: O(n²) build plus O(n³) factorisation. That is microseconds for n ≤ 50. Cap the watchlist at around 30–50 tickers (PLAN §13 item 32).

### 2.3 Random events (jumps)

After the GBM step, each ticker independently has a probability `p = 0.001` per tick of a shock:

```python
if random.random() < p:
    S *= 1 + random.choice([-1, 1]) * random.uniform(0.02, 0.05)
```

10 tickers × 2 ticks/s × 0.001 gives **about one event every 50 seconds** somewhere on the board, which is enough to make the heatmap and P&L chart move during a demo. Jumps are permanent: there is no reversion, just like real news.

### 2.4 Seeds and parameters

- `SEED_PRICES`: realistic starting prices for the 10 default tickers (AAPL 190, GOOGL 175, MSFT 420, AMZN 185, TSLA 250, NVDA 800, META 500, JPM 195, V 280, NFLX 600).
- `TICKER_PARAMS`: per-ticker `σ`/`μ`. High-σ: TSLA 0.50, NVDA 0.40. Low-σ: V 0.17, JPM 0.18.
- `DEFAULT_PARAMS = {σ: 0.25, μ: 0.05}` for unknown tickers. Their seed price is `random.uniform(50, 300)`.
  - 🔧 Replace with a **deterministic** seed derived from the symbol, e.g. `50 + (crc32(ticker) % 25000) / 100`. Then `PYPL` gets the same starting price after every restart and in every test.

## 3. Code structure

```
seed_prices.py          constants only: SEED_PRICES, TICKER_PARAMS, DEFAULT_PARAMS,
                        CORRELATION_GROUPS, INTRA_*_CORR, CROSS_GROUP_CORR, TSLA_CORR
simulator.py
├── GBMSimulator        pure, synchronous math core (no asyncio, no cache)
│   ├── __init__(tickers, dt=DEFAULT_DT, event_probability=0.001)
│   ├── step() -> dict[str, float]        advance all tickers one Δt; hot path
│   ├── add_ticker(t) / remove_ticker(t)  mutate set + rebuild Cholesky
│   ├── get_price(t) -> float | None
│   ├── get_tickers() -> list[str]
│   ├── _add_ticker_internal(t)           seed price + params, no rebuild (batch init)
│   ├── _rebuild_cholesky()               build C, L = cholesky(C); None when n ≤ 1
│   └── _pairwise_correlation(a, b)       sector rules above
└── SimulatorDataSource(MarketDataSource) asyncio adapter → PriceCache
    ├── __init__(price_cache, update_interval=0.5, event_probability=0.001)
    ├── start(tickers)    build GBMSimulator, seed cache, spawn "simulator-loop" task
    ├── stop()            cancel + await task (idempotent)
    ├── add_ticker(t)     sim.add_ticker + immediate cache.update (price available at once)
    ├── remove_ticker(t)  sim.remove_ticker + cache.remove
    ├── get_tickers()
    └── _run_loop()       while True: step → cache.update for each → sleep(interval)
```

**Why two classes:** `GBMSimulator` can be unit-tested by calling `step()` in a tight loop, with no event loop, sleeps or cache. `SimulatorDataSource` is a thin adapter that owns only lifecycle and timing. It is the only part that knows about asyncio and `PriceCache`.

### The tick (hot path)

```python
def step(self) -> dict[str, float]:
    n = len(self._tickers)
    if n == 0:
        return {}
    z = np.random.standard_normal(n)
    if self._cholesky is not None:
        z = self._cholesky @ z                       # correlate
    out = {}
    for i, t in enumerate(self._tickers):
        mu, sigma = self._params[t]["mu"], self._params[t]["sigma"]
        self._prices[t] *= math.exp((mu - 0.5 * sigma**2) * self._dt
                                    + sigma * math.sqrt(self._dt) * z[i])
        if random.random() < self._event_prob:      # jump
            self._prices[t] *= 1 + random.choice([-1, 1]) * random.uniform(0.02, 0.05)
        out[t] = round(self._prices[t], 2)
    return out
```

Internal prices keep full float precision. Only the *reported* price is rounded, so rounding error never accumulates.

### The loop

```python
async def _run_loop(self) -> None:
    while True:
        try:
            for ticker, price in self._sim.step().items():
                self._cache.update(ticker=ticker, price=price)
        except Exception:
            logger.exception("Simulator step failed")   # never let the task die
        await asyncio.sleep(self._interval)
```

All mutations happen on the event loop thread. `add_ticker` and `remove_ticker` are `async` methods called from request handlers, so they never race with `step()`. No locking is needed inside the simulator.

## 4. Lifecycle

```python
cache = PriceCache()
source = SimulatorDataSource(cache)              # normally via create_market_data_source(cache)
await source.start(["AAPL", "GOOGL", ...])       # cache already holds 10 seed prices here
await source.add_ticker("PYPL")                  # priced immediately
await source.remove_ticker("GOOGL")              # gone from sim and cache
await source.stop()
```

## 5. Interaction with the rest of the system

- **`reference_price`** 🔧 (see `MARKET_INTERFACE.md` §2.1): pass the seed price on the first `cache.update` in `start()` and `add_ticker()`, so "daily change %" means change since the simulation session started.
- **Restarts reset prices.** Prices aren't persisted, so after a container restart every ticker starts again from its seed while `avg_cost` in the DB reflects pre-restart prices. Unrealised P&L therefore jumps on restart. This is acceptable for a demo. 🔧 A cheap improvement: on `start()`, accept optional `initial_prices: dict[str, float]` and pass the last portfolio-snapshot-era prices or position `avg_cost` values, so held tickers resume near where they were.
- **Any symbol is accepted.** The simulator happily prices `ZZZZZ`. Validation is the app layer's job (`normalize_ticker` plus an optional allow-list in simulator mode, PLAN §13 item 5).

## 6. Tuning knobs

| Knob | Where | Default | Effect |
|---|---|---|---|
| `update_interval` | `SimulatorDataSource` | 0.5 s | tick rate; also scales `dt` if you pass `dt=interval/TRADING_SECONDS_PER_YEAR` |
| `event_probability` | `SimulatorDataSource` / `GBMSimulator` | 0.001 | jump frequency; set `0` in tests |
| `TICKER_PARAMS[t]["sigma"]` | `seed_prices.py` | 0.17–0.50 | how jumpy a ticker is |
| correlations | `seed_prices.py` | 0.6 / 0.5 / 0.3 | how much the board moves together |
| `dt` | `GBMSimulator` | 8.48e-8 | 🔧 a "demo speed" multiplier (e.g. `dt × 10`) makes charts more dramatic without changing σ |

🔧 Note that `update_interval` and `dt` are independent today. Changing the interval to 1 s without changing `dt` halves the apparent volatility per wall-clock second. Derive `dt` from the interval in `SimulatorDataSource.__init__`.

## 7. Determinism & testing

🔧 The simulator currently draws from the **global** `np.random` and `random` modules, so runs are not reproducible and tests can only make statistical assertions. Inject a generator:

```python
class GBMSimulator:
    def __init__(self, tickers, dt=DEFAULT_DT, event_probability=0.001, seed: int | None = None):
        self._rng = np.random.default_rng(seed)
    # step():   z = self._rng.standard_normal(n)
    #           if self._rng.random() < p: shock = self._rng.choice([-1, 1]) * self._rng.uniform(0.02, 0.05)
```

Also expose it via an optional `SIMULATOR_SEED` env var, read in the factory. E2E runs then produce identical price paths.

Test checklist (`backend/tests/market/test_simulator*.py`):

- prices stay > 0 over 10k steps, including with forced events (`event_probability=1`)
- with `event_probability=0` and fixed seed, log-returns have mean ≈ `(μ−σ²/2)Δt` and std ≈ `σ√Δt` (within tolerance over ~50k steps)
- the empirical correlation of log-returns between AAPL and MSFT is ≈ 0.6, and between AAPL and TSLA ≈ 0.3
- Cholesky succeeds for 1, 2 and 50 mixed tickers (n ≤ 1 → `None`)
- add/remove keep `_tickers`, `_prices`, `_params` and the matrix dimension consistent; duplicates are no-ops
- `SimulatorDataSource`: cache seeded on `start`, `add_ticker` prices immediately, `remove_ticker` clears the cache, `stop` is idempotent, and the loop survives an exception in `step()`

## 8. Change list (summary)

| # | Change | File |
|---|---|---|
| 1 | Inject `np.random.Generator` (+ `SIMULATOR_SEED`) | `simulator.py`, `factory.py` |
| 2 | Deterministic seed price for unknown tickers | `simulator.py` |
| 3 | Pass `reference_price` (seed) to cache | `simulator.py` |
| 4 | Derive `dt` from `update_interval` | `simulator.py` |
| 5 | Optional `initial_prices` on `start()` | `simulator.py` |
| 6 | Cholesky-safety and correlation tests | `tests/market/test_simulator.py` |
