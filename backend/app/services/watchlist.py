"""Watchlist business logic: validation, size cap, and market-source tracking."""

from __future__ import annotations

from app import db, state

from .errors import WatchlistError, WatchlistNotFoundError, normalize_ticker

MAX_WATCHLIST_SIZE = 30


def held_tickers() -> set[str]:
    """Tickers with an open position."""
    return {p["ticker"] for p in db.get_positions()}


def tracked_tickers() -> list[str]:
    """Union of watchlist and position tickers (watchlist order first)."""
    tickers = list(db.get_watchlist())
    for ticker in sorted(held_tickers()):
        if ticker not in tickers:
            tickers.append(ticker)
    return tickers


def _build_item(ticker: str, added_at: str | None) -> dict:
    update = state.price_cache.get(ticker)
    if update is None:
        price = previous_price = open_price = change_percent = None
    else:
        price = update.price
        previous_price = update.previous_price
        open_price = update.open_price if update.open_price is not None else update.price
        change_percent = round((price - open_price) / open_price * 100, 4) if open_price else 0.0
    return {
        "ticker": ticker,
        "price": price,
        "previous_price": previous_price,
        "open_price": open_price,
        "change_percent": change_percent,
        "added_at": added_at,
    }


def get_watchlist() -> list[dict]:
    """All watchlist entries with live prices, ordered by added_at."""
    return [_build_item(row["ticker"], row["added_at"]) for row in db.get_watchlist_items()]


def _get_item(ticker: str) -> dict:
    for row in db.get_watchlist_items():
        if row["ticker"] == ticker:
            return _build_item(ticker, row["added_at"])
    return _build_item(ticker, None)


async def add_ticker_with_status(ticker: str) -> tuple[dict, bool]:
    """Add a ticker; returns (WatchlistItem, created). Duplicates are idempotent."""
    ticker = normalize_ticker(ticker, WatchlistError)
    current = db.get_watchlist()
    if ticker in current:
        return _get_item(ticker), False
    if len(current) >= MAX_WATCHLIST_SIZE:
        raise WatchlistError(f"Watchlist is full (max {MAX_WATCHLIST_SIZE} tickers)")
    created = db.add_watchlist_ticker(ticker)
    source = state.market_source
    if source is not None:
        await source.add_ticker(ticker)
    return _get_item(ticker), created


async def add_ticker(ticker: str) -> dict:
    """Add a ticker to the watchlist and start tracking it. Returns the WatchlistItem."""
    item, _ = await add_ticker_with_status(ticker)
    return item


async def remove_ticker(ticker: str) -> None:
    """Remove a ticker from the watchlist.

    The market source keeps tracking it while a position is held.
    """
    ticker = normalize_ticker(ticker, WatchlistError)
    if not db.remove_watchlist_ticker(ticker):
        raise WatchlistNotFoundError(f"{ticker} is not on the watchlist")
    source = state.market_source
    if source is not None and ticker not in held_tickers():
        await source.remove_ticker(ticker)


async def sync_market_source() -> None:
    """Make the market source track exactly the union of watchlist and positions."""
    source = state.market_source
    if source is None:
        return
    desired = tracked_tickers()
    current = set(source.get_tickers())
    for ticker in current - set(desired):
        await source.remove_ticker(ticker)
    for ticker in desired:
        if ticker not in current:
            await source.add_ticker(ticker)
