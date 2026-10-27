"""Tests for DB path resolution, schema creation, seeding and transactions."""

import sqlite3
from pathlib import Path

import pytest

from app import db
from app.db import connection

EXPECTED_TABLES = {
    "users_profile",
    "watchlist",
    "positions",
    "trades",
    "portfolio_snapshots",
    "chat_messages",
}


def _tables(path: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


class TestInit:
    def test_creates_all_tables(self, db_path):
        assert EXPECTED_TABLES <= _tables(db_path)

    def test_sets_db_path(self, db_path):
        assert db.get_db_path() == db_path

    def test_seeds_default_cash(self, db_path):
        assert db.get_cash() == 10000.0

    def test_seeds_default_watchlist_in_order(self, db_path):
        assert db.get_watchlist() == list(db.DEFAULT_WATCHLIST)
        assert db.get_watchlist() == [
            "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX",
        ]

    def test_seed_added_at_strictly_increasing(self, db_path):
        items = db.get_watchlist_items()
        stamps = [i["added_at"] for i in items]
        assert stamps == sorted(stamps)
        assert len(set(stamps)) == len(stamps)

    def test_reinit_does_not_duplicate(self, db_path):
        db.set_cash(123.45)
        db.init_db(db_path)
        db.init_db(db_path)
        assert db.get_watchlist() == list(db.DEFAULT_WATCHLIST)
        assert db.get_cash() == 123.45
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 10
        finally:
            conn.close()

    def test_reinit_does_not_reseed_emptied_watchlist(self, db_path):
        for t in db.get_watchlist():
            db.remove_watchlist_ticker(t)
        db.init_db(db_path)
        assert db.get_watchlist() == []

    def test_wal_mode_enabled(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        finally:
            conn.close()

    def test_creates_parent_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(connection, "_db_path", None)
        path = tmp_path / "nested" / "deeper" / "x.db"
        db.init_db(str(path))
        assert path.exists()

    def test_env_db_path_used(self, tmp_path, monkeypatch):
        monkeypatch.setattr(connection, "_db_path", None)
        path = str(tmp_path / "env.db")
        monkeypatch.setenv("DB_PATH", path)
        assert db.get_db_path() == path
        db.init_db()
        assert Path(path).exists()
        assert db.get_db_path() == path

    def test_default_path_is_repo_db_dir(self, monkeypatch):
        monkeypatch.setattr(connection, "_db_path", None)
        monkeypatch.delenv("DB_PATH", raising=False)
        p = Path(db.get_db_path())
        assert p.name == "finally.db"
        assert p.parent.name == "db"
        assert (p.parent.parent / "backend").is_dir()


class TestTransaction:
    def test_commits_on_success(self, db_path):
        with db.transaction() as conn:
            db.set_cash(500.0, conn=conn)
        assert db.get_cash() == 500.0

    def test_rolls_back_on_exception(self, db_path):
        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                db.set_cash(1.0, conn=conn)
                db.upsert_position("AAPL", 5, 100.0, conn=conn)
                db.insert_trade("AAPL", "buy", 5, 100.0, conn=conn)
                raise RuntimeError("boom")
        assert db.get_cash() == 10000.0
        assert db.get_positions() == []
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
        finally:
            conn.close()

    def test_composed_trade_in_one_transaction(self, db_path):
        with db.transaction() as conn:
            cash = db.get_cash(conn=conn)
            db.set_cash(cash - 1900.0, conn=conn)
            db.upsert_position("AAPL", 10, 190.0, conn=conn)
            trade = db.insert_trade("AAPL", "buy", 10, 190.0, conn=conn)
            db.insert_snapshot(10000.0, conn=conn)
            # reads inside the transaction see uncommitted writes
            assert db.get_cash(conn=conn) == 8100.0
            assert db.get_position("AAPL", conn=conn)["quantity"] == 10
        assert trade["side"] == "buy"
        assert db.get_cash() == 8100.0
        assert db.get_position("AAPL") == {
            "ticker": "AAPL",
            "quantity": 10.0,
            "avg_cost": 190.0,
            "updated_at": db.get_position("AAPL")["updated_at"],
        }
        assert len(db.get_snapshots()) == 1

    def test_uses_begin_immediate(self, db_path):
        # While a transaction holds the write lock, another writer must wait/fail.
        with db.transaction() as conn:
            assert conn.in_transaction
            other = sqlite3.connect(db_path, timeout=0.05, isolation_level=None)
            try:
                with pytest.raises(sqlite3.OperationalError):
                    other.execute("BEGIN IMMEDIATE")
            finally:
                other.close()

    def test_uncommitted_writes_invisible_outside(self, db_path):
        with db.transaction() as conn:
            db.set_cash(42.0, conn=conn)
            assert db.get_cash() == 10000.0
        assert db.get_cash() == 42.0
