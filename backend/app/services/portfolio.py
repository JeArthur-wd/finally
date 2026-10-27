"""Portfolio business logic: trade execution, valuation, snapshots, reset."""

from __future__ import annotations

import asyncio
import math

from app import db, state

from .errors import TradeError, normalize_ticker
from .watchlist import MAX_WATCHLIST_SIZE, sync_market_source

QTY_EPSILON = 1e-6
PRICE_WAIT_SECONDS = 2.0
PRICE_POLL_INTERVAL = 0.1

_trade_lock = asyncio.Lock()


def _fmt_qty(value: float) -> str:
    """Format a share quantity without trailing zeros (3 -> '3', 2.5 -> '2.5')."""
    return f"{value:.4f}".rstrip("0").rstrip(".")


def get_portfolio() -> dict:
    """Current Portfolio: cash plus positions valued at live prices (avg_cost fallback)."""
    cash = round(db.get_cash(), 2)
    positions = []
    for row in db.get_positions():
        qty = row["quantity"]
        avg_cost = row["avg_cost"]
        live = state.price_cache.get_price(row["ticker"])
        current = live if live is not None else avg_cost
        market_value = qty * current
        cost_basis = qty * avg_cost
        pnl = market_value - cost_basis
        positions.append(
            {
                "ticker": row["ticker"],
                "quantity": qty,
                "avg_cost": avg_cost,
                "current_price": current,
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl / cost_basis * 100, 2) if cost_basis else 0.0,
            }
        )
    positions_value = round(float(sum(p["market_value"] for p in positions)), 2)
    return {
        "cash_balance": cash,
        "total_value": round(cash + positions_value, 2),
        "positions_value": positions_value,
        "unrealized_pnl": round(float(sum(p["unrealized_pnl"] for p in positions)), 2),
        "positions": positions,
    }


def record_snapshot() -> None:
    """Persist the current total portfolio value."""
    db.insert_snapshot(get_portfolio()["total_value"])


def get_history(limit: int = 1000) -> list[dict]:
    """Portfolio value snapshots, oldest first."""
    return [
        {"total_value": s["total_value"], "recorded_at": s["recorded_at"]}
        for s in db.get_snapshots(limit)
    ]


async def _ensure_price(ticker: str) -> float:
    """Return the cached price, starting to track the ticker first if necessary."""
    price = state.price_cache.get_price(ticker)
    if price is not None:
        return price
    watchlist = db.get_watchlist()
    if ticker not in watchlist and len(watchlist) < MAX_WATCHLIST_SIZE:
        db.add_watchlist_ticker(ticker)
    source = state.market_source
    if source is not None:
        await source.add_ticker(ticker)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + PRICE_WAIT_SECONDS
    while True:
        price = state.price_cache.get_price(ticker)
        if price is not None:
            return price
        if loop.time() >= deadline:
            raise TradeError(f"No price available for {ticker}")
        await asyncio.sleep(PRICE_POLL_INTERVAL)


def _parse_quantity(quantity: object) -> float:
    try:
        qty = float(quantity)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise TradeError(f"Invalid quantity: {quantity!r}") from None
    if not math.isfinite(qty):
        raise TradeError(f"Invalid quantity: {quantity!r}")
    qty = round(qty, 4)
    if qty <= 0:
        raise TradeError("Quantity must be greater than 0")
    return qty


async def execute_trade(ticker: str, side: str, quantity: float) -> dict:
    """Execute a market order at the current cached price and return the Trade.

    Raises TradeError with a user-facing message on any validation failure.
    """
    ticker = normalize_ticker(ticker, TradeError)
    side = side.strip().lower() if isinstance(side, str) else ""
    if side not in ("buy", "sell"):
        raise TradeError("Side must be 'buy' or 'sell'")
    qty = _parse_quantity(quantity)

    # Fail fast on selling something not held, without starting to track it.
    if side == "sell" and db.get_position(ticker) is None:
        raise TradeError(f"Insufficient shares: have 0, tried to sell {_fmt_qty(qty)}")

    await _ensure_price(ticker)

    closed = False
    async with _trade_lock:
        live = state.price_cache.get_price(ticker)
        if live is None or live <= 0:
            raise TradeError(f"No price available for {ticker}")
        price = round(live, 2)
        with db.transaction() as conn:
            cash = db.get_cash(conn=conn)
            position = db.get_position(ticker, conn=conn)
            held = position["quantity"] if position else 0.0
            cost = round(qty * price, 2)

            if side == "buy":
                if cash + 1e-9 < cost:
                    raise TradeError(f"Insufficient cash: need ${cost:,.2f}, have ${cash:,.2f}")
                new_qty = round(held + qty, 4)
                old_cost = held * position["avg_cost"] if position else 0.0
                avg_cost = round((old_cost + qty * price) / new_qty, 4)
                db.upsert_position(ticker, new_qty, avg_cost, conn=conn)
                db.set_cash(round(cash - cost, 2), conn=conn)
            else:
                if held + QTY_EPSILON < qty:
                    raise TradeError(
                        f"Insufficient shares: have {_fmt_qty(held)}, tried to sell {_fmt_qty(qty)}"
                    )
                remaining = round(held - qty, 4)
                if remaining < QTY_EPSILON:
                    db.delete_position(ticker, conn=conn)
                    closed = True
                else:
                    db.upsert_position(ticker, remaining, position["avg_cost"], conn=conn)
                db.set_cash(round(cash + cost, 2), conn=conn)

            trade = db.insert_trade(ticker, side, qty, price, conn=conn)

    source = state.market_source
    if closed and source is not None and ticker not in db.get_watchlist():
        await source.remove_ticker(ticker)

    record_snapshot()
    return {
        "id": trade["id"],
        "ticker": trade["ticker"],
        "side": trade["side"],
        "quantity": trade["quantity"],
        "price": trade["price"],
        "executed_at": trade["executed_at"],
    }


async def reset() -> None:
    """Restore the default state, resync tracked tickers, and record a snapshot."""
    async with _trade_lock:
        db.reset_user()
    await sync_market_source()
    record_snapshot()
