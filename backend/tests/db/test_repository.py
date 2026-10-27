"""Tests for the repository functions in app.db."""

import sqlite3

import pytest

from app import db


class TestCash:
    def test_set_and_get(self, db_path):
        db.set_cash(1234.56)
        assert db.get_cash() == 1234.56

    def test_unknown_user_defaults(self, db_path):
        assert db.get_cash(user_id="nobody") == 10000.0

    def test_set_creates_profile_for_new_user(self, db_path):
        db.set_cash(5.0, user_id="other")
        assert db.get_cash(user_id="other") == 5.0
        assert db.get_cash() == 10000.0


class TestWatchlist:
    def test_add_new_returns_true_and_appends(self, db_path):
        assert db.add_watchlist_ticker("PYPL") is True
        assert db.get_watchlist()[-1] == "PYPL"
        assert len(db.get_watchlist()) == 11

    def test_add_duplicate_returns_false(self, db_path):
        assert db.add_watchlist_ticker("AAPL") is False
        assert db.get_watchlist().count("AAPL") == 1

    def test_remove(self, db_path):
        assert db.remove_watchlist_ticker("TSLA") is True
        assert "TSLA" not in db.get_watchlist()

    def test_remove_absent_returns_false(self, db_path):
        assert db.remove_watchlist_ticker("ZZZZ") is False

    def test_order_preserved_after_adds(self, db_path):
        for t in ("PYPL", "AMD", "INTC"):
            db.add_watchlist_ticker(t)
        assert db.get_watchlist()[-3:] == ["PYPL", "AMD", "INTC"]

    def test_readd_moves_to_end(self, db_path):
        db.remove_watchlist_ticker("AAPL")
        db.add_watchlist_ticker("AAPL")
        assert db.get_watchlist()[-1] == "AAPL"

    def test_watchlist_items_shape_and_order(self, db_path):
        db.add_watchlist_ticker("PYPL")
        items = db.get_watchlist_items()
        assert [i["ticker"] for i in items] == db.get_watchlist()
        assert set(items[0]) == {"ticker", "added_at"}
        assert all(isinstance(i["added_at"], str) for i in items)
        assert items[-1]["ticker"] == "PYPL"

    def test_users_isolated(self, db_path):
        db.add_watchlist_ticker("PYPL", user_id="other")
        assert db.get_watchlist(user_id="other") == ["PYPL"]
        assert "PYPL" not in db.get_watchlist()


class TestPositions:
    def test_empty(self, db_path):
        assert db.get_positions() == []
        assert db.get_position("AAPL") is None

    def test_upsert_insert_then_update(self, db_path):
        db.upsert_position("AAPL", 10, 190.0)
        db.upsert_position("AAPL", 15, 191.5)
        pos = db.get_position("AAPL")
        assert pos["quantity"] == 15.0
        assert pos["avg_cost"] == 191.5
        assert isinstance(pos["updated_at"], str)
        assert len(db.get_positions()) == 1

    def test_ordered_by_ticker(self, db_path):
        for t in ("TSLA", "AAPL", "MSFT"):
            db.upsert_position(t, 1, 100.0)
        assert [p["ticker"] for p in db.get_positions()] == ["AAPL", "MSFT", "TSLA"]

    def test_shape(self, db_path):
        db.upsert_position("AAPL", 0.5, 100.0)
        assert set(db.get_positions()[0]) == {"ticker", "quantity", "avg_cost", "updated_at"}

    def test_delete(self, db_path):
        db.upsert_position("AAPL", 1, 100.0)
        db.delete_position("AAPL")
        assert db.get_position("AAPL") is None

    def test_delete_absent_is_noop(self, db_path):
        db.delete_position("NOPE")


class TestTrades:
    def test_insert_returns_row(self, db_path):
        t = db.insert_trade("AAPL", "buy", 2.5, 190.12)
        assert set(t) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
        assert t["ticker"] == "AAPL" and t["side"] == "buy"
        assert t["quantity"] == 2.5 and t["price"] == 190.12
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT ticker, side, quantity, price, user_id FROM trades WHERE id = ?",
                (t["id"],),
            ).fetchone()
        finally:
            conn.close()
        assert row == ("AAPL", "buy", 2.5, 190.12, "default")

    def test_unique_ids(self, db_path):
        a = db.insert_trade("AAPL", "buy", 1, 1.0)
        b = db.insert_trade("AAPL", "sell", 1, 1.0)
        assert a["id"] != b["id"]

    def test_invalid_side_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_trade("AAPL", "hold", 1, 1.0)


class TestSnapshots:
    def test_empty(self, db_path):
        assert db.get_snapshots() == []

    def test_ascending_order(self, db_path):
        for v in (1.0, 2.0, 3.0):
            db.insert_snapshot(v)
        snaps = db.get_snapshots()
        assert [s["total_value"] for s in snaps] == [1.0, 2.0, 3.0]
        assert set(snaps[0]) == {"total_value", "recorded_at"}

    def test_limit_returns_most_recent_ascending(self, db_path):
        for v in range(10):
            db.insert_snapshot(float(v))
        assert [s["total_value"] for s in db.get_snapshots(limit=3)] == [7.0, 8.0, 9.0]


class TestChat:
    def test_user_message_no_actions(self, db_path):
        m = db.insert_chat_message("user", "hello")
        assert m["actions"] is None
        assert set(m) == {"id", "role", "content", "actions", "created_at"}
        assert db.get_chat_messages() == [m]

    def test_actions_json_roundtrip(self, db_path):
        actions = [
            {"type": "trade", "ticker": "AAPL", "side": "buy", "quantity": 1,
             "price": 190.0, "status": "executed"},
            {"type": "watchlist", "ticker": "PYPL", "action": "add",
             "status": "failed", "error": "Watchlist full"},
        ]
        db.insert_chat_message("assistant", "done", actions)
        got = db.get_chat_messages()[0]
        assert got["actions"] == actions
        assert got["role"] == "assistant"

    def test_dict_actions_roundtrip(self, db_path):
        db.insert_chat_message("assistant", "x", {"trades": [], "watchlist_changes": []})
        assert db.get_chat_messages()[0]["actions"] == {"trades": [], "watchlist_changes": []}

    def test_empty_list_actions_preserved(self, db_path):
        db.insert_chat_message("assistant", "x", [])
        assert db.get_chat_messages()[0]["actions"] == []

    def test_limit_most_recent_ascending(self, db_path):
        for i in range(30):
            db.insert_chat_message("user" if i % 2 == 0 else "assistant", f"m{i}")
        msgs = db.get_chat_messages()
        assert len(msgs) == 20
        assert [m["content"] for m in msgs] == [f"m{i}" for i in range(10, 30)]
        assert [m["content"] for m in db.get_chat_messages(limit=2)] == ["m28", "m29"]

    def test_invalid_role_rejected(self, db_path):
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_chat_message("system", "nope")


class TestReset:
    def test_reset_restores_fresh_state(self, db_path):
        db.set_cash(5.0)
        db.upsert_position("AAPL", 3, 100.0)
        db.insert_trade("AAPL", "buy", 3, 100.0)
        db.insert_snapshot(305.0)
        db.insert_chat_message("user", "hi")
        db.remove_watchlist_ticker("AAPL")
        db.add_watchlist_ticker("PYPL")

        db.reset_user()

        assert db.get_cash() == 10000.0
        assert db.get_positions() == []
        assert db.get_snapshots() == []
        assert db.get_chat_messages() == []
        assert db.get_watchlist() == list(db.DEFAULT_WATCHLIST)
        conn = sqlite3.connect(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0
        finally:
            conn.close()

    def test_reset_only_affects_given_user(self, db_path):
        db.upsert_position("AAPL", 1, 1.0, user_id="other")
        db.upsert_position("AAPL", 1, 1.0)
        db.reset_user()
        assert db.get_positions() == []
        assert len(db.get_positions(user_id="other")) == 1

    def test_reset_inside_transaction_rolls_back(self, db_path):
        db.set_cash(5.0)
        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                db.reset_user(conn=conn)
                raise RuntimeError
        assert db.get_cash() == 5.0
