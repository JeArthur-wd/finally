"""Fixtures for LLM tests: in-memory fakes for app.db and app.services."""

from __future__ import annotations

import sys
import types
import uuid
from datetime import UTC, datetime

import pytest


class FakeTradeError(Exception):
    pass


class FakeWatchlistError(Exception):
    pass


def _make_fake_db() -> types.ModuleType:
    mod = types.ModuleType("app.db")
    mod.messages = []

    def insert_chat_message(role, content, actions=None, *, conn=None, user_id="default"):
        row = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "actions": actions,
            "created_at": datetime.now(UTC).isoformat(),
        }
        mod.messages.append(row)
        return dict(row)

    def get_chat_messages(limit=20, *, conn=None, user_id="default"):
        return [dict(m) for m in mod.messages[-limit:]]

    mod.insert_chat_message = insert_chat_message
    mod.get_chat_messages = get_chat_messages
    return mod


def _make_fake_services() -> types.ModuleType:
    mod = types.ModuleType("app.services")
    mod.TradeError = FakeTradeError
    mod.WatchlistError = FakeWatchlistError
    mod.cash = 1000.0
    mod.prices = {"AAPL": 190.0, "MSFT": 400.0}
    mod.holdings: dict[str, float] = {}
    mod.watchlist = ["AAPL", "MSFT"]
    mod.calls = []

    async def execute_trade(ticker, side, quantity):
        ticker = ticker.strip().upper()
        mod.calls.append(("trade", ticker, side, quantity))
        price = mod.prices.get(ticker)
        if price is None:
            raise FakeTradeError(f"No price available for {ticker}")
        if side == "buy":
            cost = price * quantity
            if cost > mod.cash:
                raise FakeTradeError(f"Insufficient cash: need ${cost:,.2f}, have ${mod.cash:,.2f}")
            mod.cash -= cost
            mod.holdings[ticker] = mod.holdings.get(ticker, 0) + quantity
        else:
            held = mod.holdings.get(ticker, 0)
            if held < quantity:
                raise FakeTradeError(f"Insufficient shares: have {held:g}, tried to sell {quantity:g}")
            mod.holdings[ticker] = held - quantity
        return {
            "id": "t1",
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "price": price,
            "executed_at": "now",
        }

    async def add_ticker(ticker):
        ticker = ticker.strip().upper()
        mod.calls.append(("add", ticker))
        if ticker == "BAD!":
            raise FakeWatchlistError("Invalid ticker: BAD!")
        if ticker not in mod.watchlist:
            mod.watchlist.append(ticker)
        return {"ticker": ticker, "price": None, "previous_price": None, "open_price": None,
                "change_percent": None, "added_at": "now"}

    async def remove_ticker(ticker):
        ticker = ticker.strip().upper()
        mod.calls.append(("remove", ticker))
        if ticker not in mod.watchlist:
            raise FakeWatchlistError(f"{ticker} is not on the watchlist")
        mod.watchlist.remove(ticker)

    def get_portfolio():
        return {"cash_balance": mod.cash, "total_value": mod.cash, "positions_value": 0.0,
                "unrealized_pnl": 0.0, "positions": []}

    def get_watchlist():
        return [{"ticker": t, "price": mod.prices.get(t), "previous_price": None,
                 "open_price": None, "change_percent": 0.5, "added_at": "now"}
                for t in mod.watchlist]

    mod.execute_trade = execute_trade
    mod.add_ticker = add_ticker
    mod.remove_ticker = remove_ticker
    mod.get_portfolio = get_portfolio
    mod.get_watchlist = get_watchlist
    return mod


@pytest.fixture
def fake_db(monkeypatch):
    mod = _make_fake_db()
    monkeypatch.setitem(sys.modules, "app.db", mod)
    return mod


@pytest.fixture
def fake_services(monkeypatch):
    mod = _make_fake_services()
    monkeypatch.setitem(sys.modules, "app.services", mod)
    return mod


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def fake_completion(monkeypatch):
    """Patch litellm.completion; set ``.content`` / ``.exc`` on the returned holder."""
    import litellm

    holder = types.SimpleNamespace(content=None, exc=None, calls=[])

    def completion(**kwargs):
        holder.calls.append(kwargs)
        if holder.exc is not None:
            raise holder.exc
        msg = types.SimpleNamespace(content=holder.content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    monkeypatch.setattr(litellm, "completion", completion)
    return holder
