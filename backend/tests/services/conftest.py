"""Fixtures: a temp SQLite DB, a real PriceCache with manual prices, and a fake source."""

from __future__ import annotations

import pytest

from app import db, state
from app.market import PriceCache
from app.services import portfolio as portfolio_service

from .fakes import FakeMarketSource

DEFAULT_PRICES = {
    "AAPL": 190.0,
    "GOOGL": 175.0,
    "MSFT": 420.0,
    "AMZN": 185.0,
    "TSLA": 250.0,
    "NVDA": 800.0,
    "META": 500.0,
    "JPM": 200.0,
    "V": 280.0,
    "NFLX": 600.0,
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Initialise a temp DB and fresh singletons; returns (cache, source)."""
    db.init_db(str(tmp_path / "t.db"))
    cache = PriceCache()
    for ticker, price in DEFAULT_PRICES.items():
        cache.update(ticker, price)
    source = FakeMarketSource(cache, auto_prices={"PYPL": 70.0})
    source.tickers = list(DEFAULT_PRICES)
    monkeypatch.setattr(state, "price_cache", cache)
    monkeypatch.setattr(state, "market_source", source)
    monkeypatch.setattr(portfolio_service, "PRICE_WAIT_SECONDS", 0.3)
    return cache, source
