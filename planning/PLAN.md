# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, % change
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (volume-mounted)               │
│  Background task: market data polling/sim        │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, volume-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real data via Massive API if key provided

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no docker-compose for production, no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── db/                   # Schema definitions, seed data, migration logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # Volume mount target (SQLite file lives here at runtime)
│   └── .gitkeep              # Directory exists in repo; finally.db is gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── docker-compose.yml        # Optional convenience wrapper
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions and seed logic. The backend lazily initializes the database on first request — creating tables and seeding default data if the SQLite file doesn't exist or is empty.
- **`db/`** at the top level is the runtime volume mount point. The SQLite file (`db/finally.db`) is created here by the backend and persists across container restarts via Docker volume.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required: OpenRouter API key for LLM chat functionality
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Massive (Polygon.io) API key for real market data
# If not set, the built-in market simulator is used (recommended for most users)
MASSIVE_API_KEY=

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- The backend reads `.env` from the project root (mounted into the container or read via docker `--env-file`)

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface. The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., tech stocks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic seed prices (e.g., AAPL ~$190, GOOGL ~$175, etc.)
- Runs as an in-process background task — no external dependencies

### Massive API (Optional)

- REST API polling (not WebSocket) — simpler, works on all tiers
- Polls for the union of all watched tickers on a configurable interval
- Free tier (5 calls/min): poll every 15 seconds
- Paid tiers: poll every 2-15 seconds depending on tier
- Parses REST response into the same format as the simulator

### Shared Price Cache

- A single background task (simulator or Massive poller) writes to an in-memory price cache
- The cache holds the latest price, previous price, and timestamp for each ticker
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- Server pushes price updates for all tickers known to the system at a regular cadence (~500ms) — in the single-user model this is equivalent to the user's watchlist
- Each SSE event contains ticker, price, previous price, timestamp, and change direction
- Client handles reconnection automatically (EventSource has built-in retry)

---

## 7. Database

### SQLite with Lazy Initialization

The backend checks for the SQLite database on startup (or first request). If the file doesn't exist or tables are missing, it creates the schema and seeds default data. This means:

- No separate migration step
- No manual database setup
- Fresh Docker volumes start with a clean, seeded database automatically

### Schema

All tables include a `user_id` column defaulting to `"default"`. This is hardcoded for now (single-user) but enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded every 30 seconds by a background task, and immediately after each trade execution.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — trades executed, watchlist changes made; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

---

## 8. API Endpoints

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive complete JSON response (message + executed actions) |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) |

---

## 9. LLM Integration

When writing code to make calls to LLMs, use cerebras-inference skill to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads recent conversation history from the `chat_messages` table
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM via LiteLLM → OpenRouter, requesting structured output, using the cerebras-inference skill
5. Parses the complete structured JSON response
6. Auto-executes any trades or watchlist changes specified in the response
7. Stores the message and executed actions in `chat_messages`
8. Returns the complete JSON response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

### Structured Output Schema

The LLM is instructed to respond with JSON matching this schema:

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute. Each trade goes through the same validation as manual trades (sufficient cash for buys, sufficient shares for sells)
- `watchlist_changes` (optional): Array of watchlist modifications

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

If a trade fails validation (e.g., insufficient cash), the error is included in the chat response so the LLM can inform the user.

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling OpenRouter. This enables:
- Fast, free, reproducible E2E tests
- Development without an API key
- CI/CD pipelines

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), daily change %, and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, using data from `portfolio_snapshots`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, % change
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history, loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Canvas-based charting library preferred (Lightweight Charts or Recharts) for performance
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000.

### Docker Volume

The SQLite database persists via a named Docker volume:

```bash
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

The `db/` directory in the project root maps to `/app/db` in the container. The backend writes `finally.db` to this path.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume mount, port mapping, and `.env` file
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

### Optional Cloud Deployment

The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory as a stretch goal, but is not part of the core build.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: simulator generates valid prices, GBM math is correct, Massive API response parsing works, both implementations conform to the abstract interface
- Portfolio: trade execution logic, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow
- API routes: correct status codes, response shapes, error handling

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image.

**Environment**: Tests run with `LLM_MOCK=true` by default for speed and determinism.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message, receive a response, trade execution appears inline
- SSE resilience: disconnect and verify reconnection

---

## 13. Review: Questions, Clarifications & Simplifications

*Added by documentation review, 2026-10-26. Each item should be resolved (answered inline above, or struck) before the relevant agent starts work. Items are ordered by how likely they are to cause integration bugs between agents.*

### A. Gaps likely to cause bugs between agents

1. **API request/response shapes are unspecified.** The frontend and backend will be built by different agents. Section 8 lists paths but no JSON shapes. Without them the two sides will guess differently. Add a contract (here or in `planning/API_CONTRACT.md`) for every endpoint, including:
   - `GET /api/portfolio` fields (e.g. `cash_balance`, `total_value`, `positions[]` with `ticker, quantity, avg_cost, current_price, market_value, unrealized_pnl, unrealized_pnl_pct`)
   - `POST /api/portfolio/trade` success body (updated portfolio? the trade record?)
   - `POST /api/chat` response: `{message, trades: [{ticker, side, quantity, price, status: "executed"|"failed", error?}], watchlist_changes: [...]}`. This is the shape the frontend renders inline, which is different from the LLM's raw output.
   - `GET /api/portfolio/history`: `[{total_value, recorded_at}]`
   - A single error format, e.g. `{"error": "Insufficient cash: need $1,900.00, have $1,200.00"}` with HTTP 400 for validation failures and 404 for unknown tickers on DELETE.

2. **The SSE payload doesn't match the doc.** §6 says "each SSE event contains ticker, price, previous price…". The implemented `backend/app/market/stream.py` sends one event holding a **dict of all tickers** (`data: {"AAPL": {...}, "GOOGL": {...}}`), and only when the cache version changes. Update §6 so the frontend agent parses the real format.

3. **Removing a ticker from the watchlist while you hold a position in it.** `SimulatorDataSource.remove_ticker()` also removes the ticker from `PriceCache`. If the user holds shares in that ticker, it then has no price, so portfolio valuation, the heatmap and sells all break. Decide one of:
   - (a) The market data source tracks the **union of watchlist + held positions**. Recommended; §6 already hints at "all tickers known to the system".
   - (b) Block removing a watched ticker while a position is open.

4. **Can you trade a ticker that is not on the watchlist?** If yes (e.g. the AI buys PYPL), it needs a live price first. Proposed rule: a trade on an untracked ticker starts tracking it (adds it to the watchlist), then fills at the first price it gets. If no, the trade bar and the LLM need a clear error.

5. **Ticker validation.** What happens on `POST /api/watchlist {"ticker": "ZZZZZ"}`? The simulator will make up a price for any string (`DEFAULT_PARAMS` plus a random seed price), and Massive will return nothing. Specify:
   - normalisation (uppercase, trim)
   - an allowed pattern (e.g. `^[A-Z.]{1,6}$`)
   - whether unknown symbols are accepted in simulator mode

6. **What "daily change %" in the watchlist measures.** Nothing in the system stores a daily open or previous close. The simulator only has tick-to-tick `change`. Pick one: change since the backend started (seed price), or since the frontend page loaded. Recommended: since session start. Add an `open_price` to `PriceUpdate` or the watchlist response, so all clients show the same number.

7. **Who keeps the live header total value up to date?** Either the frontend recomputes `cash + Σ qty × live price` from SSE ticks (recommended: no extra endpoint traffic), or it polls `GET /api/portfolio`. Say which, so the P&L numbers in the header, the positions table and the heatmap agree.

8. **Mock LLM behaviour must be specified for the E2E tests.** "Deterministic mock responses" is too vague for the test agent to write assertions against. Define the mock rules, e.g.:
   - a message containing `buy <N> <TICKER>` returns that trade
   - `add <TICKER>` returns a watchlist add
   - anything else returns a fixed message with no actions

   The E2E scenario "trade execution appears inline" depends on this.

### B. Clarifications needed

9. **Numeric precision.** Quantities and cash are SQLite `REAL` (floats), so repeated trades will drift (e.g. `0.30000000000000004` shares). Specify:
   - rounding: quantity to 4–6 decimal places, cash and prices to 2 dp
   - a minimum trade quantity (> 0)
   - that a sell bringing quantity to ~0 **deletes** the position row

10. **Average cost on sells.** Confirm that avg cost stays unchanged on a sell (standard), and resets when a position is fully closed and reopened. Is realized P&L tracked or shown anywhere, or only unrealized? If only unrealized, say so.

11. **`users_profile` is inconsistent with the rule that "all tables include `user_id`".** Its key is `id`. Either rename it to `user_id` or note the exception.

12. **When does lazy initialisation happen?** §4/§7 say "on startup (or first request)". Pick one; startup (FastAPI lifespan) is simpler and also starts the market data source with the seeded watchlist. Also specify how the DB path is resolved (e.g. a `DB_PATH` env var defaulting to `<project_root>/db/finally.db`), so `uv run` locally and `/app/db` in Docker both work.

13. **The P&L chart is empty on first launch.** The first snapshot comes 30 seconds after start. Record a snapshot at startup (and/or when the history is empty) so the chart has a starting point. Also: is `portfolio_snapshots` ever pruned? At 30-second intervals it grows by about 2,880 rows per day. That's fine for SQLite, but the history endpoint may want a limit or downsampling.

14. **Chat details:**
    - How many prior messages go into the prompt (e.g. last 20)?
    - What happens when `OPENROUTER_API_KEY` is missing or the LLM call fails or times out? The app should still start and the chat should return a friendly error, not a 500.
    - Do failed trades from the chat get fed back to the LLM for a second response, or only reported in the reply? §9 says "so the LLM can inform the user", which would need a second call. Recommendation: no second call; append the failures to the response with templated text.
    - Structured outputs in strict mode usually need every field present. Tell the LLM `trades` and `watchlist_changes` are **required but may be empty arrays** rather than optional.
    - Are quantities always in shares? If the user says "buy $1,000 of AAPL", the LLM must convert using the price in its context. State this in the system prompt.

15. **Concurrent trades.** A manual trade and a chat trade could run at the same time. Do each trade's validation and write inside one SQLite transaction (`BEGIN IMMEDIATE`) so cash can't go negative.

16. **Massive mode and the SSE cadence.** With a 15-second poll, prices change only every 15 seconds while SSE checks every 500 ms. That's fine with version-based change detection, but sparklines will be sparse. Accept this explicitly so nobody "fixes" it.

17. **Empty and loading states.** These aren't specified for:
    - the heatmap and positions table with no positions
    - the main chart before any ticks arrive
    - the chat on first load (is there a greeting?)
    - a missing `.env` at container start, which makes `docker run --env-file .env` fail. Start scripts should copy `.env.example` → `.env` if it's missing, or warn.

18. **Chart data history.** The main chart only has data since page load. Should the frontend buffer ticks for **all** tickers from the start, so clicking a ticker shows its history immediately? Recommended: yes, with a cap per ticker, e.g. the last 500 points.

### C. Opportunities to simplify

19. **Drop `docker-compose.yml`** from the root. It's "optional convenience" next to the start scripts, so it's a second way to do the same thing that has to be kept in sync. Keep only `test/docker-compose.test.yml` if the E2E setup needs it.

20. **Use natural primary keys.** `watchlist` and `positions` already have `UNIQUE(user_id, ticker)`. Making that the primary key and dropping the UUID `id` columns removes needless ID generation and makes upserts simpler (`INSERT … ON CONFLICT(user_id, ticker) DO UPDATE`).

21. **Pick one charting library.** §10 says "canvas-based … (Lightweight Charts or Recharts)", but Recharts is SVG, not canvas, and Lightweight Charts has no treemap. Recommended:
    - Lightweight Charts for the main chart and the P&L chart
    - plain inline SVG `<polyline>` for sparklines (no library)
    - a small hand-rolled squarified treemap (positions are few)

    State the choice so the frontend agent doesn't pull in two or three chart libraries.

22. **Replace §6 with a pointer.** Market data is built and documented in `MARKET_DATA_SUMMARY.md`. Keeping a second description in §6 has already let the two drift apart (see item 2). Cut §6 to a few lines plus a link.

23. **Simplify the E2E setup.** A Playwright container plus compose adds a lot of setup. Running Playwright on the host against a container started by the normal start script (with `LLM_MOCK=true`) is simpler. Also, the "SSE resilience: disconnect and verify reconnection" scenario is hard to make deterministic in Playwright. Consider covering it with a frontend unit test of the connection-status logic and dropping it from E2E.

24. **Trim frontend unit test scope.** Testing that the "price flash animation triggers correctly" is brittle (timers plus CSS). Focus unit tests on the pure logic instead: P&L calculations, treemap layout, SSE message parsing.

25. **Decide "optionally opens the browser" in the start scripts.** Make it either always on or a flag (`--open`), so agents don't have to guess.

26. **Consider a reset endpoint.** A simple `POST /api/reset` (cash back to $10k, positions/trades/snapshots cleared, default watchlist restored) is cheap to add. It makes demos and E2E tests far simpler than deleting the Docker volume, and E2E tests that buy and sell otherwise depend on each other's state.

### D. Second-pass findings

27. **Chat history can't be reloaded.** `chat_messages` is written to but no endpoint reads it. After a page refresh the chat panel is empty even though the history exists. Either add `GET /api/chat/history` or state that the panel starts fresh each page load. The same applies to `trades`: it is written but never read. Either add `GET /api/portfolio/trades` (useful for a trade log in the UI and for the AI's context) or say explicitly that it is audit-only.

28. **Is `OPENROUTER_API_KEY` really required?** §5 says it is, but §9 says mock mode allows "development without an API key". Make the app start without the key and only fail the chat. Also specify what `.env.example` contains.

29. **Node 20 is past end-of-life** (April 2026). Use Node 22 or 24 LTS in the Dockerfile's Stage 1. Also specify `uv sync --frozen` so the image matches the lockfile exactly.

30. **Static export and FastAPI wiring rules.** These are worth stating so the frontend and backend agents get them right first time:
    - Next.js `output: 'export'` disallows `next/image` optimisation, API routes and server components that fetch at request time.
    - FastAPI must register every `/api/*` router **before** mounting `StaticFiles(directory="static", html=True)` at `/`, or the static mount will shadow the API.
    - Don't add `GZipMiddleware`; it buffers responses and breaks SSE.

31. **Two directories called `db`.** `backend/db/` (schema/seed code) and the top-level `db/` (runtime volume) are easily confused, and the existing backend code lives under `backend/app/`. Suggest `backend/app/db/` for the code and keep `db/` only as the volume mount.

32. **Watchlist size limit.** Each add or remove rebuilds the simulator's Cholesky correlation matrix, and the UI is a dense grid. A cap (e.g. 30 tickers) gives a clear error instead of degrading. Also say what happens on adding a duplicate: return 409, or accept it silently (idempotent)? Idempotent is simpler for the LLM path.

33. **Snapshot task when prices are missing.** The 30-second snapshot background task should skip, or fall back to avg cost, for any held ticker without a cached price. Otherwise it records a misleading drop in total value at startup, before the first tick arrives.

34. **Exact profit/loss colours.** The palette gives the yellow, blue and purple accents but not the green and red used for price flashes, P&L and the heatmap. Specify them, e.g. `#26a69a` / `#ef5350`, so the heatmap, flashes and table match. Consider whether the heatmap colour should be on a gradient scaled by % P&L or just two colours.

35. **Simplify the health check.** `GET /api/health` can simply return `{"status": "ok"}`. If Docker `HEALTHCHECK` is wanted, note that `python:3.12-slim` has no `curl`, so the check would use a Python one-liner. Or drop the Docker `HEALTHCHECK` entirely, since the start scripts don't need it.
