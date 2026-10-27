"""Deterministic mock LLM used when LLM_MOCK=true (contract §6, five rules)."""

from __future__ import annotations

import os
import re

from .models import LLMResponse, LLMTrade, LLMWatchlistChange

MOCK_DEFAULT_MESSAGE = (
    "I'm FinAlly, your AI trading assistant (mock mode). Try 'buy 5 AAPL' or 'add PYPL'."
)

_TICKER = r"([A-Za-z][A-Za-z.]{0,5})"
_QTY = r"(\d+(?:\.\d+)?|\.\d+)"

_TRADE_RE = re.compile(rf"\b(buy|sell)\s+{_QTY}\s+{_TICKER}(?![A-Za-z.])", re.IGNORECASE)
_ADD_RE = re.compile(rf"\b(?:add|watch)\s+{_TICKER}(?![A-Za-z.])", re.IGNORECASE)
_REMOVE_RE = re.compile(rf"\bremove\s+{_TICKER}(?![A-Za-z.])", re.IGNORECASE)


def is_mock_enabled() -> bool:
    """Return True when LLM_MOCK is set to "true" (case-insensitive)."""
    return os.environ.get("LLM_MOCK", "").strip().lower() == "true"


def _format_qty(raw: str) -> str:
    """Render a quantity without a pointless trailing '.0'."""
    return f"{float(raw):g}"


def mock_response(user_message: str) -> LLMResponse:
    """Apply the mock rules, in order, to the user's message."""
    text = user_message or ""

    m = _TRADE_RE.search(text)
    if m:
        side = m.group(1).lower()
        qty_str = _format_qty(m.group(2))
        ticker = m.group(3).upper()
        verb = "Buying" if side == "buy" else "Selling"
        return LLMResponse(
            message=f"{verb} {qty_str} shares of {ticker}.",
            trades=[LLMTrade(ticker=ticker, side=side, quantity=float(m.group(2)))],
            watchlist_changes=[],
        )

    m = _ADD_RE.search(text)
    if m:
        ticker = m.group(1).upper()
        return LLMResponse(
            message=f"Adding {ticker} to your watchlist.",
            trades=[],
            watchlist_changes=[LLMWatchlistChange(ticker=ticker, action="add")],
        )

    m = _REMOVE_RE.search(text)
    if m:
        ticker = m.group(1).upper()
        return LLMResponse(
            message=f"Removing {ticker} from your watchlist.",
            trades=[],
            watchlist_changes=[LLMWatchlistChange(ticker=ticker, action="remove")],
        )

    return LLMResponse(message=MOCK_DEFAULT_MESSAGE, trades=[], watchlist_changes=[])
