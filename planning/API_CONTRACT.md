# FinAlly — Team Contract (binding)

*Written by the team lead on 2026-10-27. It resolves the open items in PLAN.md §13. Where this file and PLAN.md disagree, **this file wins**. Need a change? Message the lead (and anyone affected) and get agreement before you diverge. Don't change it on your own.*

---

## 0. Team, ownership, and rules of engagement

| Agent | Owns (only edit these) |
|---|---|
| **Database Engineer** (`db-engineer`) | `backend/app/db/**`, `backend/tests/db/**` |
| **Backend API Engineer** (`api-engineer`) | `backend/app/main.py`, `backend/app/state.py`, `backend/app/services/**`, `backend/app/routes/**` (except `chat`), `backend/app/market/**` (small changes only; see §4), `backend/tests/api/**`, `backend/tests/services/**` |
| **LLM Engineer** (`llm-engineer`) | `backend/app/llm/**`, `backend/tests/llm/**` |
| **Frontend Engineer** (`frontend-engineer`) | `frontend/**` |
| **DevOps Engineer** (`devops-engineer`) | `Dockerfile`, `.dockerignore`, `scripts/**`, `.env.example`, `db/.gitkeep`, root `.gitignore`, `README.md` (the run section) |
| **Integration Tester** (`integration-tester`) | `test/**`, `planning/ISSUES.md` |

Rules:
- **Don't edit files another agent owns.** If you need a change there, ask the owner (SendMessage if you have it, otherwise write it in `planning/ISSUES.md`, addressed to them).
- Backend dependencies are already installed: `litellm`, `python-dotenv`, and dev `httpx`. If you need another one, ask the lead. Only one agent at a time should touch `pyproject.toml`/`uv.lock`.
- **Don't run `git commit` or `git push`.** The lead commits.
- Python style: ruff config in `backend/pyproject.toml`, type hints, module docstrings. Match the existing `app/market/` code.
- Every backend agent writes pytest unit tests for its own code. The frontend uses Vitest + React Testing Library.
- When you finish, report: the files you created, how to run your tests, the test results, and any deviations from this contract.

---

## 1. Backend layout

```
backend/app/
  main.py          # FastAPI app + lifespan (api-engineer)
  state.py         # singletons: price_cache, market_source (api-engineer)
  market/          # existing — done
  db/              # schema + repository (db-engineer)
  services/        # portfolio.py, watchlist.py — business logic (api-engineer)
  routes/          # portfolio.py, watchlist.py, system.py (api-engineer)
  llm/             # client, prompts, mock, chat service + chat router (llm-engineer)
```

The top-level `db/` is **only** the runtime volume. It holds no code.

### Environment
- `DB_PATH`: SQLite file path. Default: `<repo_root>/db/finally.db`, computed from `Path(__file__)`. Docker sets `DB_PATH=/app/db/finally.db`. Create the parent dir if it's missing.
- `STATIC_DIR`: the frontend export to serve. Default `backend/static`. If the directory doesn't exist, skip the static mount (API-only dev mode).
- `OPENROUTER_API_KEY`: optional. **The app must start without it.** Only the chat degrades.
- `MASSIVE_API_KEY`: optional (existing behaviour).
- `LLM_MOCK`: `"true"` turns on the deterministic mock LLM.
- `main.py` calls `load_dotenv()` on `<repo_root>/.env` if that file exists (`override=False`).

### Startup (FastAPI lifespan), in order
1. `db.init_db()`: create the tables and seed them if they're empty. Idempotent.
2. Tracked tickers = **union of watchlist tickers and position tickers**. Start the market source with that list.
3. Record one portfolio snapshot right away (held tickers without a cached price fall back to `avg_cost`).
4. Start a background task that records a snapshot every 30 s.
5. On shutdown: cancel the task, then `await market_source.stop()`.

Wiring: include every `/api/*` router **before** `app.mount("/", StaticFiles(directory=STATIC_DIR, html=True))`. **Don't add GZipMiddleware**: it breaks SSE.

---

## 2. Database (db-engineer)

SQLite via the stdlib `sqlite3`. Turn on WAL mode. Every connection uses `row_factory = sqlite3.Row`. Timestamps are ISO-8601 UTC strings (`datetime.now(UTC).isoformat()`).

### Schema (PLAN §7, with these changes)
- `users_profile(id TEXT PK DEFAULT 'default', cash_balance REAL NOT NULL DEFAULT 10000.0, created_at TEXT)`. Its key stays `id`; this is a documented exception to the `user_id` rule.
- `watchlist(user_id TEXT NOT NULL DEFAULT 'default', ticker TEXT NOT NULL, added_at TEXT, PRIMARY KEY(user_id, ticker))`: natural primary key, no UUID.
- `positions(user_id, ticker, quantity REAL, avg_cost REAL, updated_at, PRIMARY KEY(user_id, ticker))`: natural primary key.
- `trades(id TEXT PK uuid4, user_id, ticker, side CHECK(side IN ('buy','sell')), quantity REAL, price REAL, executed_at)`: append-only, audit-only (no read endpoint).
- `portfolio_snapshots(id TEXT PK uuid4, user_id, total_value REAL, recorded_at)`
- `chat_messages(id TEXT PK uuid4, user_id, role CHECK(role IN ('user','assistant')), content TEXT, actions TEXT NULL, created_at)`
- Seed data: user `default` with cash 10000.0, plus watchlist AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX, inserted in that order with increasing `added_at`.
- Put the schema SQL in `backend/app/db/schema.sql`, or a Python string constant.

### Public API: `from app.db import ...`
Every function takes `user_id: str = "default"` as a keyword argument. Functions marked `conn` accept an optional `conn: sqlite3.Connection | None = None`. When `conn` is given, they use it and don't commit, so callers can compose them inside `transaction()`. When it isn't given, they open their own connection and commit.

```python
def init_db(db_path: str | None = None) -> None          # create + seed if needed; sets module-level path
def get_db_path() -> str
@contextmanager
def transaction() -> Iterator[sqlite3.Connection]        # BEGIN IMMEDIATE ... COMMIT / ROLLBACK on exception

def get_cash(*, conn=None, user_id="default") -> float
def set_cash(value: float, *, conn=None, user_id="default") -> None

def get_watchlist(*, conn=None, user_id="default") -> list[str]            # ordered by added_at ASC
def get_watchlist_items(*, conn=None, user_id="default") -> list[dict]     # [{ticker, added_at}] ordered by added_at ASC (added 2026-10-27)
def add_watchlist_ticker(ticker: str, *, conn=None, user_id="default") -> bool   # False if already present
def remove_watchlist_ticker(ticker: str, *, conn=None, user_id="default") -> bool  # False if absent

def get_positions(*, conn=None, user_id="default") -> list[dict]   # [{ticker, quantity, avg_cost, updated_at}] ordered by ticker
def get_position(ticker: str, *, conn=None, user_id="default") -> dict | None
def upsert_position(ticker: str, quantity: float, avg_cost: float, *, conn=None, user_id="default") -> None
def delete_position(ticker: str, *, conn=None, user_id="default") -> None

def insert_trade(ticker: str, side: str, quantity: float, price: float, *, conn=None, user_id="default") -> dict  # returns the row as a dict

def insert_snapshot(total_value: float, *, conn=None, user_id="default") -> None
def get_snapshots(limit: int = 1000, *, conn=None, user_id="default") -> list[dict]  # most recent `limit`, returned ASC: [{total_value, recorded_at}]

def insert_chat_message(role: str, content: str, actions: dict | None = None, *, conn=None, user_id="default") -> dict
def get_chat_messages(limit: int = 20, *, conn=None, user_id="default") -> list[dict]  # most recent `limit`, ASC; actions parsed from JSON

def reset_user(*, conn=None, user_id="default") -> None   # cash=10000, clear positions/trades/snapshots/chat, restore default watchlist
```

Tests use a `tmp_path` DB (`init_db(str(tmp_path / "t.db"))`). Never touch the real DB in tests.

---

## 3. Business rules (api-engineer implements them in `app/services/`)

- **Ticker normalisation:** `ticker.strip().upper()`, which must match `^[A-Z][A-Z.]{0,5}$`. Otherwise return 400 `"Invalid ticker: ..."`. In simulator mode any valid-pattern symbol is accepted.
- **Watchlist:** capped at 30 tickers (400 when full). Adding a duplicate is **idempotent** (200, no error).
- **Removing a watchlist ticker** removes it from the market source **only if no position is held** in it. Prices for held tickers always keep flowing.
- **Trading a ticker with no cached price** (not tracked yet): add it to the watchlist and the market source, then wait up to 2 s (polling every 0.1 s) for a price. If none arrives, return 400 `"No price available for X"`.
- **Quantity:** must be > 0. Round to 4 dp. Fill price = current cache price rounded to 2 dp. Round cash to 2 dp after each trade.
- **Buy:** needs `cash >= qty*price`, else 400 `"Insufficient cash: need $1,900.00, have $1,200.00"`. New avg_cost = weighted average.
- **Sell:** needs `held >= qty` (tolerance 1e-6), else 400 `"Insufficient shares: have 3, tried to sell 5"`. avg_cost stays unchanged. If remaining qty < 1e-6, **delete the position**. If the ticker is also no longer on the watchlist, remove it from the market source.
- Realized P&L is **not** tracked. Only unrealized.
- **Concurrency:** each trade's validation and writes happen inside one `db.transaction()` (BEGIN IMMEDIATE), guarded by a module-level `asyncio.Lock`.
- **After each successful trade:** record a snapshot.
- **Portfolio valuation:** `market_value = qty * (cache price or avg_cost if no price yet)`; `total_value = cash + Σ market_value`.
- **Service functions** in `app/services/` (the LLM engineer imports these):
  ```python
  class TradeError(Exception): ...          # message is user-facing
  class WatchlistError(Exception): ...
  async def execute_trade(ticker: str, side: str, quantity: float) -> dict   # returns Trade (see §5); raises TradeError
  async def add_ticker(ticker: str) -> dict       # returns WatchlistItem; raises WatchlistError
  async def remove_ticker(ticker: str) -> None    # raises WatchlistError (not found → 404 at route level)
  def get_portfolio() -> dict                     # Portfolio shape (§5)
  def get_watchlist() -> list[dict]               # [WatchlistItem]
  def record_snapshot() -> None
  async def reset() -> None                       # db.reset_user + resync market source tickers + snapshot
  ```
  Export them from `app/services/__init__.py`.

---

## 4. SSE: `GET /api/stream/prices` (existing; one addition)

One event per cache change, holding **all** tickers:
```
data: {"AAPL": {"ticker":"AAPL","price":190.5,"previous_price":190.42,"open_price":190.0,"timestamp":1761580000.123,"change":0.08,"change_percent":0.042,"direction":"up"}, "GOOGL": {...}}
```
- **Addition (api-engineer):** `open_price` is the first price the cache saw for that ticker this backend session. It is **the basis for "daily change %"** everywhere: `(price - open_price) / open_price * 100`. Implement it in `PriceCache` (track the first price per ticker; clear it on `remove`) and in `PriceUpdate.to_dict()`. Keep the existing 73 market tests green.
- Prices tick every ~500 ms in simulator mode. In Massive mode they tick every ~15 s, so sparse sparklines are expected (don't "fix" this).
- `timestamp` is Unix **seconds** (a float).

---

## 5. REST API

All JSON. Errors are always `{"error": "<human message>"}`, with **400** for validation failures, **404** for unknown resources, and **500** never for expected cases. FastAPI's own 422 validation errors must also be reshaped to `{"error": ...}` with status 400.

### Shapes
```ts
type Position = { ticker: string; quantity: number; avg_cost: number; current_price: number;
                  market_value: number; unrealized_pnl: number; unrealized_pnl_pct: number }   // pct as percent, e.g. 5.25
type Portfolio = { cash_balance: number; total_value: number; positions_value: number;
                   unrealized_pnl: number; positions: Position[] }
type Trade = { id: string; ticker: string; side: "buy"|"sell"; quantity: number; price: number; executed_at: string }
type WatchlistItem = { ticker: string; price: number | null; previous_price: number | null;
                       open_price: number | null; change_percent: number | null; added_at: string }  // change_percent vs open_price
type Snapshot = { total_value: number; recorded_at: string }
type ChatAction =
  | { type: "trade"; ticker: string; side: "buy"|"sell"; quantity: number; price: number | null;
      status: "executed" | "failed"; error?: string }
  | { type: "watchlist"; ticker: string; action: "add"|"remove"; status: "executed" | "failed"; error?: string }
type ChatMessage = { id: string; role: "user"|"assistant"; content: string; actions: ChatAction[] | null; created_at: string }
type ChatResponse = { message: ChatMessage /* the assistant msg */; actions: ChatAction[] }
```

### Endpoints
| Method | Path | Body | 2xx response |
|---|---|---|---|
| GET | `/api/health` | | `{"status":"ok"}` |
| GET | `/api/portfolio` | | `Portfolio` |
| POST | `/api/portfolio/trade` | `{ticker, quantity, side}` | `{trade: Trade, portfolio: Portfolio}` |
| GET | `/api/portfolio/history` | | `Snapshot[]` (ASC, max 1000) |
| GET | `/api/watchlist` | | `WatchlistItem[]` (ordered by added_at) |
| POST | `/api/watchlist` | `{ticker}` | `WatchlistItem` (201 if new, 200 if already present) |
| DELETE | `/api/watchlist/{ticker}` | | `{"ticker": "X"}` (404 if not on the watchlist) |
| POST | `/api/chat` | `{message}` | `ChatResponse` |
| GET | `/api/chat/history` | | `ChatMessage[]` (last 50, ASC) |
| POST | `/api/reset` | | `Portfolio` (fresh state) |
| GET | `/api/stream/prices` | | SSE (§4) |

---

## 6. LLM (llm-engineer): `app/llm/`

- Use the **cerebras-inference skill** (`.claude/skills/cerebras/SKILL.md`): LiteLLM → OpenRouter, model `openrouter/openai/gpt-oss-120b`, Cerebras provider, structured outputs.
- LLM output schema (strict). **Every field is required.** The arrays may be empty:
  `{ message: string, trades: [{ticker, side: "buy"|"sell", quantity: number}], watchlist_changes: [{ticker, action: "add"|"remove"}] }`
- Context in the prompt: cash, positions with P&L, the watchlist with live prices and change %, total value, and the **last 20** chat messages.
- System prompt: "FinAlly, an AI trading assistant". Be concise and data-driven. Quantities are **always shares**: convert dollar amounts using the price from the context, and round down to 4 dp. Execute when the user asks or agrees. Manage the watchlist proactively.
- Flow: save the user message → call the LLM (timeout 30 s) → execute watchlist changes, then trades, through `app.services` → collect `ChatAction[]` → **no second LLM call**. If any action failed, append a templated line to the message, e.g. `"\n\n⚠️ Could not buy 50 AAPL: Insufficient cash: ..."` → save the assistant message with its actions → return `ChatResponse`.
- Failures (no API key, timeout, malformed JSON): return HTTP **200** with an assistant message such as `"Sorry — I couldn't reach the AI service right now (…). Please try again."` and `actions: []`. Never a 500.
- Expose `router` (an APIRouter with `POST /api/chat` and `GET /api/chat/history`) from `app/llm/__init__.py`. The api-engineer includes it in `main.py`.

### Mock mode (`LLM_MOCK=true`): deterministic rules, case-insensitive, applied to the user message
1. `buy <N> <TICKER>` → message `"Buying <N> shares of <TICKER>."`, with that trade.
2. `sell <N> <TICKER>` → message `"Selling <N> shares of <TICKER>."`, with that trade.
3. `add <TICKER>` (`watch <TICKER>` also works) → `"Adding <TICKER> to your watchlist."`, with a watchlist add.
4. `remove <TICKER>` → `"Removing <TICKER> from your watchlist."`, with a watchlist remove.
5. Anything else → `"I'm FinAlly, your AI trading assistant (mock mode). Try 'buy 5 AAPL' or 'add PYPL'."`, with no actions.

Mock mode goes through the **same** execution, persistence and failure-template path as the real LLM.

---

## 7. Frontend (frontend-engineer)

- Next.js (App Router) + TypeScript + Tailwind, with `output: 'export'`. The build output is `frontend/out/`. No `next/image` optimisation, no API routes, no request-time server fetching: everything is client-side.
- Dev: the backend runs on `:8000`. Use relative `/api/...` URLs everywhere. For `next dev`, add `rewrites` to `http://localhost:8000` **only when `NODE_ENV === 'development'`**.
- Charts: **Lightweight Charts** for the main chart and the P&L chart. **Inline SVG `<polyline>`** for sparklines. A **hand-rolled squarified treemap** for the heatmap. No other chart libraries.
- Colours: background `#0d1117`, panels `#161b22`, borders `#30363d`, up `#26a69a`, down `#ef5350`, accent yellow `#ecad0a`, blue `#209dd7`, purple `#753991` (submit buttons). The heatmap shades by P&L % on a gradient clamped at ±5%.
- Buffer SSE ticks for **all** tickers from page load, capped at 500 points per ticker, so the main chart has history as soon as a ticker is clicked.
- The header's total value is recomputed on the client: `cash + Σ qty × live SSE price`. Refetch `/api/portfolio` after each trade or chat response, and every 15 s. The positions table and heatmap use the same live calculation.
- Connection dot: green = open, yellow = connecting/reconnecting, red = closed/error for more than 5 s.
- Chat: load `/api/chat/history` on mount. Show a static greeting when the history is empty. Show a loading indicator while waiting. Render `ChatAction`s inline as small confirmation chips (green for executed, red for failed, with the error). After a response with actions, refresh the portfolio and watchlist.
- Empty states: the positions/heatmap area says "No positions yet — buy something with the trade bar or ask FinAlly". The main chart says "Waiting for data…".
- **`data-testid`s required for E2E:** `watchlist`, `watchlist-row-<TICKER>`, `watchlist-price-<TICKER>`, `watchlist-remove-<TICKER>`, `watchlist-add-input`, `watchlist-add-button`, `cash-balance`, `total-value`, `connection-status` (with `data-status="connected|reconnecting|disconnected"`), `trade-ticker`, `trade-quantity`, `trade-buy`, `trade-sell`, `trade-error`, `positions-table`, `position-row-<TICKER>`, `heatmap`, `heatmap-cell-<TICKER>`, `pnl-chart`, `main-chart`, `chat-panel`, `chat-input`, `chat-send`, `chat-loading`, `chat-message` (one per message, plus `data-role`), `chat-action` (with `data-status`).
- **E2E display conventions** (added 2026-10-27):
  - Money renders as `$10,000.00`, with a `$` sign and thousands separators. A negative amount uses a leading `-`.
  - `trade-error` and failed `chat-action` chips show the backend's error text verbatim, e.g. "Insufficient cash: …". Every `chat-action` chip contains its ticker.
  - `main-chart` shows the selected ticker's symbol as text and contains a `<canvas>`. `pnl-chart` also contains a `<canvas>`.
  - The empty-state text includes "No positions yet".
  - `watchlist-row-*` elements render in `added_at` order inside `watchlist`. `watchlist-remove-<T>` may appear only on hover, but it must still be clickable after a hover.
- Unit tests (Vitest): P&L/portfolio maths, treemap layout, SSE message parsing, connection-status logic.

---

## 8. Docker & scripts (devops-engineer)

- Multi-stage `Dockerfile`: **Node 22** slim → `npm ci && npm run build` → Python 3.12 slim + uv → `uv sync --frozen --no-dev` → copy `frontend/out` to `/app/backend/static` → `ENV DB_PATH=/app/db/finally.db STATIC_DIR=/app/backend/static` → `EXPOSE 8000` → `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000` (run from `/app/backend`). No Docker HEALTHCHECK.
- No root `docker-compose.yml`.
- Scripts: `start_mac.sh`, `stop_mac.sh`, `start_windows.ps1`, `stop_windows.ps1`. They're idempotent. Container name `finally`, image `finally`, volume `finally-data:/app/db`, port 8000, `--env-file .env`. If `.env` is missing, copy it from `.env.example` and print a warning. `--build` forces a rebuild. The scripts open the browser by default; `--no-open` skips that. Stop removes the container but **keeps the volume**.
- `.env.example`: `OPENROUTER_API_KEY=`, `MASSIVE_API_KEY=`, `LLM_MOCK=false`, each with a comment.
- Root `.gitignore` additions: `db/*.db*`, `frontend/node_modules`, `frontend/out`, `frontend/.next`, `backend/static`, `test/node_modules`, `test/test-results`, `test/playwright-report`.

---

## 9. E2E (integration-tester): `test/`

- Simplified per §13.23: Playwright runs **on the host** (`test/package.json`, `test/playwright.config.ts`) against a container. Helper scripts `test/run_e2e.sh` and `test/run_e2e.ps1` start the image as container `finally-e2e` on port **8001**, with `LLM_MOCK=true` and a throwaway volume. They then run the tests and tear down. `BASE_URL` overrides the target (e.g. `http://localhost:8000` for a local dev server).
- Each test calls `POST /api/reset` in `beforeEach`.
- Scenarios: fresh start (10 tickers, $10,000.00, prices change, connection dot connected); add and remove a ticker; buy (cash down, position row appears); sell (cash up, the position disappears when fully sold); heatmap cell and P&L chart render; mock chat `buy 1 AAPL` shows a response plus an executed action chip, and a position appears; a failed chat trade (`buy 100000 AAPL`) shows a failed chip. SSE reconnection is **out of scope** for E2E; it's covered by frontend unit tests.
- File each failure in `planning/ISSUES.md` (owner, repro, expected vs actual, logs), then message the owner.
