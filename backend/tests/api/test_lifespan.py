"""App lifespan and wiring tests (real DB init, fake market source)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import db, main, state
from app.market import PriceCache
from tests.services.fakes import FakeMarketSource


def test_lifespan_starts_source_with_union_and_snapshots(tmp_path, monkeypatch):
    db_path = tmp_path / "sub" / "life.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    cache = PriceCache()
    monkeypatch.setattr(state, "price_cache", cache)
    monkeypatch.setattr(state, "market_source", None)
    created: list[FakeMarketSource] = []

    def factory(c):
        src = FakeMarketSource(c, auto_prices={"AAPL": 190.0})
        created.append(src)
        return src

    monkeypatch.setattr(main, "create_market_data_source", factory)

    # Pre-seed a held position not on the watchlist so the union matters.
    db.init_db(str(db_path))
    db.upsert_position("PYPL", 2, 60.0)

    app = main.create_app(static_dir=str(tmp_path / "nostatic"))
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        (src,) = created
        assert src.started
        assert "PYPL" in src.tickers and "AAPL" in src.tickers
        assert state.market_source is src
        snaps = db.get_snapshots()
        assert len(snaps) == 1
        assert snaps[0]["total_value"] == 10000.0 + 120.0  # avg_cost fallback for PYPL
    assert src.stopped
    assert state.market_source is None


def test_static_mount_after_api(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>hi</html>")
    monkeypatch.setattr(state, "market_source", None)
    db.init_db(str(tmp_path / "s.db"))
    app = main.create_app(use_lifespan=False, static_dir=str(static))
    with TestClient(app) as client:
        assert client.get("/").text == "<html>hi</html>"
        assert client.get("/api/health").json() == {"status": "ok"}
