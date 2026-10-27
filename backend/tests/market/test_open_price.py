"""Tests for session open_price tracking and the per-call stream router."""

from __future__ import annotations

from app.market import PriceCache, PriceUpdate, create_stream_router


def test_open_price_is_first_price_seen():
    cache = PriceCache()
    first = cache.update("AAPL", 190.0)
    assert first.open_price == 190.0
    cache.update("AAPL", 195.0)
    latest = cache.update("AAPL", 200.0)
    assert latest.open_price == 190.0
    assert cache.get_open_price("AAPL") == 190.0
    assert latest.to_dict()["open_price"] == 190.0


def test_open_price_rounded():
    cache = PriceCache()
    assert cache.update("AAPL", 190.12345).open_price == 190.12


def test_open_price_cleared_on_remove():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.remove("AAPL")
    assert cache.get_open_price("AAPL") is None
    assert cache.update("AAPL", 210.0).open_price == 210.0


def test_open_price_per_ticker():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("MSFT", 420.0)
    cache.update("AAPL", 191.0)
    assert cache.get("MSFT").open_price == 420.0
    assert cache.get("AAPL").open_price == 190.0


def test_to_dict_open_price_fallback_when_unset():
    update = PriceUpdate(ticker="AAPL", price=190.5, previous_price=190.0, timestamp=1.0)
    assert update.open_price is None
    assert update.to_dict()["open_price"] == 190.5


def test_stream_router_fresh_per_call():
    r1 = create_stream_router(PriceCache())
    r2 = create_stream_router(PriceCache())
    assert r1 is not r2
    assert [r.path for r in r1.routes] == ["/api/stream/prices"]
    assert [r.path for r in r2.routes] == ["/api/stream/prices"]
