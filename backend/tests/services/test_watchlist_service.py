"""Tests for watchlist service rules."""

from __future__ import annotations

import pytest

from app import db, services
from app.services import WatchlistError, WatchlistNotFoundError, normalize_ticker


@pytest.mark.parametrize("raw,expected", [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("V", "V")])
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "1ABC", "TOOLONG", "AB-C", ".A", None])
def test_normalize_ticker_rejects(raw):
    with pytest.raises(ValueError):
        normalize_ticker(raw)


def test_get_watchlist_items_shape(env):
    cache, _ = env
    cache.update("AAPL", 209.0)  # open price stays 190
    items = services.get_watchlist()
    assert [i["ticker"] for i in items][:3] == ["AAPL", "GOOGL", "MSFT"]
    aapl = items[0]
    assert aapl["price"] == 209.0
    assert aapl["previous_price"] == 190.0
    assert aapl["open_price"] == 190.0
    assert aapl["change_percent"] == 10.0
    assert aapl["added_at"]


async def test_add_new_and_idempotent(env):
    _, source = env
    item, created = await services.add_ticker_with_status(" pypl ")
    assert created is True
    assert item["ticker"] == "PYPL" and item["price"] == 70.0
    assert "PYPL" in source.tickers
    item2, created2 = await services.add_ticker_with_status("PYPL")
    assert created2 is False and item2["ticker"] == "PYPL"
    assert db.get_watchlist().count("PYPL") == 1


async def test_add_invalid(env):
    with pytest.raises(WatchlistError, match="Invalid ticker"):
        await services.add_ticker("123")


async def test_add_cap(env):
    for i in range(20):
        await services.add_ticker("T" + chr(ord("A") + i))
    assert len(db.get_watchlist()) == 30
    with pytest.raises(WatchlistError, match="full"):
        await services.add_ticker("ZZZ")


async def test_remove_unknown(env):
    with pytest.raises(WatchlistNotFoundError):
        await services.remove_ticker("PYPL")


async def test_remove_untracks_when_not_held(env):
    cache, source = env
    await services.remove_ticker("googl")
    assert "GOOGL" not in db.get_watchlist()
    assert "GOOGL" not in source.tickers
    assert cache.get("GOOGL") is None


async def test_remove_keeps_tracking_held(env):
    cache, source = env
    await services.execute_trade("AAPL", "buy", 1)
    await services.remove_ticker("AAPL")
    assert "AAPL" not in db.get_watchlist()
    assert "AAPL" in source.tickers
    assert cache.get_price("AAPL") is not None
    assert "AAPL" in services.tracked_tickers()
