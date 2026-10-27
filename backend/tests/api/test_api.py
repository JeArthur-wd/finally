"""REST API tests: status codes, response shapes and error format."""

from __future__ import annotations

PORTFOLIO_KEYS = {"cash_balance", "total_value", "positions_value", "unrealized_pnl", "positions"}
POSITION_KEYS = {
    "ticker",
    "quantity",
    "avg_cost",
    "current_price",
    "market_value",
    "unrealized_pnl",
    "unrealized_pnl_pct",
}
WATCH_KEYS = {"ticker", "price", "previous_price", "open_price", "change_percent", "added_at"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_portfolio_fresh(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == PORTFOLIO_KEYS
    assert body["cash_balance"] == 10000.0
    assert body["total_value"] == 10000.0
    assert body["positions"] == []


def test_buy_and_sell_flow(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "aapl", "quantity": 10, "side": "buy"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"trade", "portfolio"}
    assert set(body["trade"]) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert body["trade"]["ticker"] == "AAPL"
    assert body["portfolio"]["cash_balance"] == 8100.0
    (pos,) = body["portfolio"]["positions"]
    assert set(pos) == POSITION_KEYS and pos["quantity"] == 10

    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "sell"})
    assert r.status_code == 200
    assert r.json()["portfolio"]["positions"] == []
    assert r.json()["portfolio"]["cash_balance"] == 10000.0


def test_insufficient_cash(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "NVDA", "quantity": 100, "side": "buy"})
    assert r.status_code == 400
    assert r.json() == {"error": "Insufficient cash: need $80,000.00, have $10,000.00"}


def test_insufficient_shares(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 3, "side": "buy"})
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 5, "side": "sell"})
    assert r.status_code == 400
    assert r.json() == {"error": "Insufficient shares: have 3, tried to sell 5"}


def test_trade_validation_errors_are_400(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL"})
    assert r.status_code == 400
    assert set(r.json()) == {"error"}
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": "x", "side": "buy"})
    assert r.status_code == 400 and "error" in r.json()
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 0, "side": "buy"})
    assert r.status_code == 400 and "greater than 0" in r.json()["error"]
    r = client.post("/api/portfolio/trade", json={"ticker": "$$", "quantity": 1, "side": "buy"})
    assert r.status_code == 400 and r.json()["error"].startswith("Invalid ticker")


def test_history(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    r = client.get("/api/portfolio/history")
    assert r.status_code == 200
    hist = r.json()
    assert len(hist) == 1
    assert set(hist[0]) == {"total_value", "recorded_at"}


def test_watchlist_get(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 10
    assert items[0]["ticker"] == "AAPL"
    assert all(set(i) == WATCH_KEYS for i in items)


def test_watchlist_add_created_then_idempotent(client):
    r = client.post("/api/watchlist", json={"ticker": " pypl "})
    assert r.status_code == 201
    assert set(r.json()) == WATCH_KEYS and r.json()["ticker"] == "PYPL"
    r = client.post("/api/watchlist", json={"ticker": "PYPL"})
    assert r.status_code == 200
    assert len(client.get("/api/watchlist").json()) == 11


def test_watchlist_add_invalid(client):
    r = client.post("/api/watchlist", json={"ticker": "ZZZZZZZ"})
    assert r.status_code == 400
    assert r.json()["error"].startswith("Invalid ticker")
    r = client.post("/api/watchlist", json={})
    assert r.status_code == 400 and "error" in r.json()


def test_watchlist_delete(client, env):
    _, source = env
    r = client.delete("/api/watchlist/googl")
    assert r.status_code == 200
    assert r.json() == {"ticker": "GOOGL"}
    assert "GOOGL" not in source.tickers
    r = client.delete("/api/watchlist/GOOGL")
    assert r.status_code == 404
    assert "error" in r.json()


def test_watchlist_remove_keeps_tracking_held(client, env):
    cache, source = env
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 2, "side": "buy"})
    assert client.delete("/api/watchlist/AAPL").status_code == 200
    assert "AAPL" in source.tickers
    pos = client.get("/api/portfolio").json()["positions"][0]
    assert pos["current_price"] == cache.get_price("AAPL")


def test_reset(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 2, "side": "buy"})
    client.delete("/api/watchlist/MSFT")
    r = client.post("/api/reset")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == PORTFOLIO_KEYS
    assert body["cash_balance"] == 10000.0 and body["positions"] == []
    tickers = [i["ticker"] for i in client.get("/api/watchlist").json()]
    assert len(tickers) == 10 and "MSFT" in tickers


def test_unknown_api_route_error_shape(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    assert "error" in r.json()


def test_chat_router_included(client):
    paths = {route.path for route in client.app.routes}
    assert "/api/chat" in paths
    assert "/api/stream/prices" in paths
