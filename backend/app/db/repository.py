"""Repository functions: all reads and writes against the FinAlly database.

Every function accepts an optional ``conn``. When given, it is used as-is and
nothing is committed, so calls can be composed inside ``transaction()``. When
omitted, the function opens its own connection (and commits, for writes).
"""

from __future__ import annotations

import json
import sqlite3
import uuid

from .connection import now_iso, read_conn, seed_default_watchlist, write_conn
from .schema import DEFAULT_CASH, DEFAULT_USER_ID

Conn = sqlite3.Connection | None


# --- Cash -------------------------------------------------------------------


def get_cash(*, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> float:
    """Return the user's cash balance (DEFAULT_CASH if the profile is missing)."""
    with read_conn(conn) as c:
        row = c.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)
        ).fetchone()
    return float(row["cash_balance"]) if row else DEFAULT_CASH


def set_cash(value: float, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> None:
    """Set the user's cash balance, creating the profile if needed."""
    with write_conn(conn) as c:
        c.execute(
            """
            INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET cash_balance = excluded.cash_balance
            """,
            (user_id, float(value), now_iso()),
        )


# --- Watchlist ----------------------------------------------------------------


def get_watchlist(*, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> list[str]:
    """Return watched tickers ordered by added_at ascending."""
    with read_conn(conn) as c:
        rows = c.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at ASC, rowid ASC",
            (user_id,),
        ).fetchall()
    return [r["ticker"] for r in rows]


def get_watchlist_items(*, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """Return watchlist rows as [{ticker, added_at}] ordered by added_at ascending."""
    with read_conn(conn) as c:
        rows = c.execute(
            "SELECT ticker, added_at FROM watchlist WHERE user_id = ? "
            "ORDER BY added_at ASC, rowid ASC",
            (user_id,),
        ).fetchall()
    return [{"ticker": r["ticker"], "added_at": r["added_at"]} for r in rows]


def add_watchlist_ticker(
    ticker: str, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID
) -> bool:
    """Add a ticker. Returns False if it was already present."""
    with write_conn(conn) as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?)",
            (user_id, ticker, now_iso()),
        )
        return cur.rowcount > 0


def remove_watchlist_ticker(
    ticker: str, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID
) -> bool:
    """Remove a ticker. Returns False if it was not present."""
    with write_conn(conn) as c:
        cur = c.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker)
        )
        return cur.rowcount > 0


# --- Positions ----------------------------------------------------------------


def _position_dict(row: sqlite3.Row) -> dict:
    return {
        "ticker": row["ticker"],
        "quantity": float(row["quantity"]),
        "avg_cost": float(row["avg_cost"]),
        "updated_at": row["updated_at"],
    }


def get_positions(*, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> list[dict]:
    """Return all positions as [{ticker, quantity, avg_cost, updated_at}] ordered by ticker."""
    with read_conn(conn) as c:
        rows = c.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? ORDER BY ticker ASC",
            (user_id,),
        ).fetchall()
    return [_position_dict(r) for r in rows]


def get_position(
    ticker: str, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID
) -> dict | None:
    """Return one position or None."""
    with read_conn(conn) as c:
        row = c.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()
    return _position_dict(row) if row else None


def upsert_position(
    ticker: str,
    quantity: float,
    avg_cost: float,
    *,
    conn: Conn = None,
    user_id: str = DEFAULT_USER_ID,
) -> None:
    """Insert or replace the quantity/avg_cost for a position."""
    with write_conn(conn) as c:
        c.execute(
            """
            INSERT INTO positions (user_id, ticker, quantity, avg_cost, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, ticker) DO UPDATE SET
                quantity = excluded.quantity,
                avg_cost = excluded.avg_cost,
                updated_at = excluded.updated_at
            """,
            (user_id, ticker, float(quantity), float(avg_cost), now_iso()),
        )


def delete_position(ticker: str, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> None:
    """Delete a position (no-op if absent)."""
    with write_conn(conn) as c:
        c.execute("DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker))


# --- Trades -------------------------------------------------------------------


def insert_trade(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    *,
    conn: Conn = None,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """Append a trade and return {id, ticker, side, quantity, price, executed_at}."""
    trade = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "side": side,
        "quantity": float(quantity),
        "price": float(price),
        "executed_at": now_iso(),
    }
    with write_conn(conn) as c:
        c.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trade["id"],
                user_id,
                trade["ticker"],
                trade["side"],
                trade["quantity"],
                trade["price"],
                trade["executed_at"],
            ),
        )
    return trade


# --- Portfolio snapshots --------------------------------------------------------


def insert_snapshot(
    total_value: float, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID
) -> None:
    """Record a portfolio value snapshot."""
    with write_conn(conn) as c:
        c.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, float(total_value), now_iso()),
        )


def get_snapshots(
    limit: int = 1000, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID
) -> list[dict]:
    """Return the most recent ``limit`` snapshots in ascending time order."""
    with read_conn(conn) as c:
        rows = c.execute(
            "SELECT total_value, recorded_at FROM portfolio_snapshots WHERE user_id = ? "
            "ORDER BY recorded_at DESC, rowid DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    return [
        {"total_value": float(r["total_value"]), "recorded_at": r["recorded_at"]}
        for r in reversed(rows)
    ]


# --- Chat messages ----------------------------------------------------------------


def _chat_dict(row: sqlite3.Row) -> dict:
    raw = row["actions"]
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "actions": json.loads(raw) if raw is not None else None,
        "created_at": row["created_at"],
    }


def insert_chat_message(
    role: str,
    content: str,
    actions: dict | list | None = None,
    *,
    conn: Conn = None,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """Store a chat message (``actions`` JSON-encoded). Returns the message dict.

    The returned dict has the ChatMessage shape: {id, role, content, actions, created_at}.
    ``actions`` may be any JSON-serialisable value (typically a list of ChatAction dicts).
    """
    msg = {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": now_iso(),
    }
    with write_conn(conn) as c:
        c.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                msg["id"],
                user_id,
                role,
                content,
                json.dumps(actions) if actions is not None else None,
                msg["created_at"],
            ),
        )
    return msg


def get_chat_messages(
    limit: int = 20, *, conn: Conn = None, user_id: str = DEFAULT_USER_ID
) -> list[dict]:
    """Return the most recent ``limit`` chat messages in ascending order."""
    with read_conn(conn) as c:
        rows = c.execute(
            "SELECT id, role, content, actions, created_at FROM chat_messages "
            "WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    return [_chat_dict(r) for r in reversed(rows)]


# --- Reset ------------------------------------------------------------------------

_RESET_TABLES = ("positions", "trades", "portfolio_snapshots", "chat_messages", "watchlist")


def reset_user(*, conn: Conn = None, user_id: str = DEFAULT_USER_ID) -> None:
    """Restore a user to the fresh-start state.

    Cash back to 10,000; positions, trades, snapshots and chat cleared; default
    watchlist restored.
    """
    with write_conn(conn) as c:
        set_cash(DEFAULT_CASH, conn=c, user_id=user_id)
        for table in _RESET_TABLES:
            c.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        seed_default_watchlist(c, user_id)
