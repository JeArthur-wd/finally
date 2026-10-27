"""Service-layer exceptions and shared ticker helpers."""

from __future__ import annotations

import re

TICKER_PATTERN = re.compile(r"^[A-Z][A-Z.]{0,5}$")


class TradeError(Exception):
    """A trade failed validation. The message is user-facing."""


class WatchlistError(Exception):
    """A watchlist change failed validation. The message is user-facing."""


class WatchlistNotFoundError(WatchlistError):
    """The ticker is not on the watchlist (mapped to HTTP 404)."""


def normalize_ticker(ticker: object, error_cls: type[Exception] = ValueError) -> str:
    """Return ``ticker.strip().upper()`` or raise ``error_cls`` if it doesn't match the pattern."""
    if not isinstance(ticker, str):
        raise error_cls(f"Invalid ticker: {ticker!r}")
    normalized = ticker.strip().upper()
    if not TICKER_PATTERN.match(normalized):
        raise error_cls(f"Invalid ticker: {ticker.strip() or repr(ticker)}")
    return normalized
