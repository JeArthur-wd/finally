"""Business logic for portfolio and watchlist (shared by the REST routes and the LLM)."""

from .errors import TradeError, WatchlistError, WatchlistNotFoundError, normalize_ticker
from .portfolio import execute_trade, get_history, get_portfolio, record_snapshot, reset
from .watchlist import (
    MAX_WATCHLIST_SIZE,
    add_ticker,
    add_ticker_with_status,
    get_watchlist,
    remove_ticker,
    sync_market_source,
    tracked_tickers,
)

__all__ = [
    "MAX_WATCHLIST_SIZE",
    "TradeError",
    "WatchlistError",
    "WatchlistNotFoundError",
    "add_ticker",
    "add_ticker_with_status",
    "execute_trade",
    "get_history",
    "get_portfolio",
    "get_watchlist",
    "normalize_ticker",
    "record_snapshot",
    "remove_ticker",
    "reset",
    "sync_market_source",
    "tracked_tickers",
]
