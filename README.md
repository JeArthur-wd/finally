# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

## Quick Start

Requires Docker. The start scripts create `.env` from `.env.example` if it's missing,
build the image on first run, start the container and open http://localhost:8000.

**macOS / Linux**
```bash
./scripts/start_mac.sh            # build if needed, run, open browser
./scripts/start_mac.sh --build    # force a rebuild (after code changes)
./scripts/start_mac.sh --no-open  # don't open the browser
./scripts/stop_mac.sh             # stop + remove the container (data is kept)
```

**Windows (PowerShell)**
```powershell
.\scripts\start_windows.ps1            # build if needed, run, open browser
.\scripts\start_windows.ps1 --build    # force a rebuild
.\scripts\start_windows.ps1 --no-open  # don't open the browser
.\scripts\stop_windows.ps1             # stop + remove the container (data is kept)
```

**Manual Docker**
```bash
cp .env.example .env              # optionally add OPENROUTER_API_KEY
docker build -t finally .
docker run -d --name finally -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

Your portfolio lives in the `finally-data` Docker volume and survives restarts and rebuilds.
To start fresh, run `docker volume rm finally-data` after stopping.

The scripts are idempotent: running start again replaces the container, and stop is safe
when nothing is running.

### Local development (without Docker)

```bash
cd backend && uv sync --extra dev && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev   # proxies /api to :8000
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | No | OpenRouter API key for AI chat; without it the app runs and only chat is unavailable |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing) |
| `DB_PATH` | No | SQLite file path (default `db/finally.db`; `/app/db/finally.db` in Docker) |

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project
├── planning/    # Project documentation and agent contracts
├── test/        # Playwright E2E tests
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Start/stop helpers
```

## License

See [LICENSE](LICENSE).
