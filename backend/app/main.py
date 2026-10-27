"""FastAPI application: lifespan wiring, API routers, and the static frontend mount."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db, services, state
from app.llm import router as chat_router
from app.market import create_market_data_source, create_stream_router
from app.routes import install_error_handlers, portfolio_router, system_router, watchlist_router

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SNAPSHOT_INTERVAL_SECONDS = 30.0

_env_file = REPO_ROOT / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)


async def _snapshot_loop(interval: float) -> None:
    """Record a portfolio snapshot every `interval` seconds until cancelled."""
    while True:
        await asyncio.sleep(interval)
        try:
            services.record_snapshot()
        except Exception:  # keep the loop alive on transient DB errors
            logger.exception("Failed to record portfolio snapshot")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Startup: init DB, start market data for tracked tickers, snapshot. Shutdown: stop all."""
    db.init_db()
    source = create_market_data_source(state.price_cache)
    state.configure(source=source)
    await source.start(services.tracked_tickers())
    services.record_snapshot()
    task = asyncio.create_task(_snapshot_loop(SNAPSHOT_INTERVAL_SECONDS))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await source.stop()
        state.configure(source=None)


def create_app(*, use_lifespan: bool = True, static_dir: str | None = None) -> FastAPI:
    """Build the FastAPI app. Tests pass ``use_lifespan=False`` and configure ``state`` themselves."""
    app = FastAPI(title="FinAlly", lifespan=lifespan if use_lifespan else None)
    install_error_handlers(app)

    # All /api routers must be registered before the static mount at "/".
    app.include_router(system_router)
    app.include_router(portfolio_router)
    app.include_router(watchlist_router)
    app.include_router(chat_router)
    app.include_router(create_stream_router(state.price_cache))

    static_path = Path(static_dir or os.environ.get("STATIC_DIR") or BACKEND_DIR / "static")
    if static_path.is_dir():
        app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
    else:
        logger.info("Static dir %s not found; serving API only", static_path)
    return app


app = create_app()
