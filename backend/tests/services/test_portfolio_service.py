"""Tests for trade execution, valuation, snapshots and reset."""

from __future__ import annotations

import pytest

from app import db, services
from app.services import TradeError


async def test_buy_updates_cash_position_and_snapshot(env):
    trade = await services.execute_trade(" aapl ", "BUY", 10)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10
    assert trade["price"] == 190.0
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert db.get_cash() == 8100.0
    pos = db.get_position("AAPL")
    assert pos["quantity"] == 10 and pos["avg_cost"] == 190.0
    assert len(db.get_snapshots()) == 1


async def test_buy_weighted_average_cost(env):
    cache, _ = env
    await services.execute_trade("AAPL", "buy", 10)
    cache.update("AAPL", 210.0)
    await services.execute_trade("AAPL", "buy", 10)
    pos = db.get_position("AAPL")
    assert pos["quantity"] == 20
    assert pos["avg_cost"] == 200.0


async def test_insufficient_cash_message(env):
    db.set_cash(1200.0)
    with pytest.raises(TradeError, match=r"^Insufficient cash: need \$1,900\.00, have \$1,200\.00$"):
        await services.execute_trade("AAPL", "buy", 10)
    assert db.get_cash() == 1200.0
    assert db.get_position("AAPL") is None


async def test_insufficient_shares_message(env):
    await services.execute_trade("AAPL", "buy", 3)
    with pytest.raises(TradeError, match=r"^Insufficient shares: have 3, tried to sell 5$"):
        await services.execute_trade("AAPL", "sell", 5)


async def test_sell_not_held(env):
    with pytest.raises(TradeError, match="have 0, tried to sell 1"):
        await services.execute_trade("AAPL", "sell", 1)


async def test_sell_keeps_avg_cost(env):
    cache, _ = env
    await services.execute_trade("AAPL", "buy", 10)
    cache.update("AAPL", 150.0)  # sell at a loss
    await services.execute_trade("AAPL", "sell", 4)
    pos = db.get_position("AAPL")
    assert pos["quantity"] == 6
    assert pos["avg_cost"] == 190.0
    assert db.get_cash() == 8100.0 + 600.0


async def test_sell_to_zero_deletes_position(env):
    await services.execute_trade("AAPL", "buy", 0.3)
    await services.execute_trade("AAPL", "sell", 0.1)
    await services.execute_trade("AAPL", "sell", 0.2)
    assert db.get_position("AAPL") is None
    assert db.get_cash() == 10000.0


async def test_closing_unwatched_position_stops_tracking(env):
    cache, source = env
    await services.execute_trade("AAPL", "buy", 1)
    await services.remove_ticker("AAPL")
    assert "AAPL" in source.tickers  # still held -> still tracked
    await services.execute_trade("AAPL", "sell", 1)
    assert "AAPL" not in source.tickers


@pytest.mark.parametrize("qty", [0, -1, float("nan"), 0.00001])
async def test_invalid_quantity(env, qty):
    with pytest.raises(TradeError):
        await services.execute_trade("AAPL", "buy", qty)


async def test_quantity_rounded_to_4dp(env):
    trade = await services.execute_trade("AAPL", "buy", 1.123456)
    assert trade["quantity"] == 1.1235


async def test_invalid_side_and_ticker(env):
    with pytest.raises(TradeError, match="Side"):
        await services.execute_trade("AAPL", "hold", 1)
    with pytest.raises(TradeError, match="Invalid ticker"):
        await services.execute_trade("123", "buy", 1)


async def test_fill_price_rounded(env):
    cache, _ = env
    cache.update("AAPL", 190.0)
    trade = await services.execute_trade("AAPL", "buy", 1)
    assert trade["price"] == round(trade["price"], 2)


async def test_trade_untracked_ticker_adds_and_fills(env):
    _, source = env
    trade = await services.execute_trade("pypl", "buy", 2)
    assert trade["price"] == 70.0
    assert "PYPL" in db.get_watchlist()
    assert "PYPL" in source.tickers


async def test_trade_untracked_ticker_without_price(env):
    with pytest.raises(TradeError, match="^No price available for ZZZZ$"):
        await services.execute_trade("ZZZZ", "buy", 1)


def test_portfolio_valuation(env):
    cache, _ = env
    db.upsert_position("AAPL", 10, 100.0)
    db.upsert_position("XYZ", 2, 50.0)  # no cached price -> avg_cost fallback
    db.set_cash(5000.0)
    cache.update("AAPL", 110.0)
    p = services.get_portfolio()
    assert p["cash_balance"] == 5000.0
    assert p["positions_value"] == 1200.0
    assert p["total_value"] == 6200.0
    assert p["unrealized_pnl"] == 100.0
    aapl = next(x for x in p["positions"] if x["ticker"] == "AAPL")
    assert aapl == {
        "ticker": "AAPL",
        "quantity": 10,
        "avg_cost": 100.0,
        "current_price": 110.0,
        "market_value": 1100.0,
        "unrealized_pnl": 100.0,
        "unrealized_pnl_pct": 10.0,
    }
    xyz = next(x for x in p["positions"] if x["ticker"] == "XYZ")
    assert xyz["current_price"] == 50.0 and xyz["unrealized_pnl"] == 0.0


def test_record_snapshot_and_history(env):
    services.record_snapshot()
    hist = services.get_history()
    assert hist == [{"total_value": 10000.0, "recorded_at": hist[0]["recorded_at"]}]


async def test_reset(env):
    _, source = env
    await services.execute_trade("PYPL", "buy", 1)
    await services.remove_ticker("AAPL")
    await services.reset()
    assert db.get_cash() == 10000.0
    assert db.get_positions() == []
    assert db.get_watchlist()[0] == "AAPL"
    assert "PYPL" not in source.tickers
    assert "AAPL" in source.tickers
    assert len(db.get_snapshots()) == 1
