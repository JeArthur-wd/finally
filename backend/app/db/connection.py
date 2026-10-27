"""SQLite connection management: DB path resolution, lazy init, transactions."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .schema import DEFAULT_CASH, DEFAULT_USER_ID, DEFAULT_WATCHLIST, SCHEMA_SQL

# app/db/connection.py -> parents: db, app, backend, <repo_root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = _REPO_ROOT / "db" / "finally.db"

_db_path: str | None = None
_init_lock = threading.Lock()


def now_iso() -> str:
    """Current time as an ISO-8601 UTC string."""
    return datetime.now(UTC).isoformat()


def get_db_path() -> str:
    """Return the active DB path (set by init_db, else $DB_PATH, else the repo default)."""
    if _db_path is not None:
        return _db_path
    return os.environ.get("DB_PATH") or str(DEFAULT_DB_PATH)


def connect(db_path: str | None = None) -> sqlite3.Connection:
    """Open a new autocommit connection (transactions are managed explicitly)."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Open a connection and run a ``BEGIN IMMEDIATE`` transaction.

    Commits on normal exit, rolls back if the block raises. The connection is
    closed afterwards.
    """
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def write_conn(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Use the caller's connection as-is (no commit), or run in a fresh transaction."""
    if conn is not None:
        yield conn
    else:
        with transaction() as new_conn:
            yield new_conn


@contextmanager
def read_conn(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Use the caller's connection, or open (and close) a fresh autocommit one."""
    if conn is not None:
        yield conn
        return
    new_conn = connect()
    try:
        yield new_conn
    finally:
        new_conn.close()


def seed_default_watchlist(conn: sqlite3.Connection, user_id: str = DEFAULT_USER_ID) -> None:
    """Insert the default watchlist with strictly increasing ``added_at`` timestamps."""
    base = datetime.now(UTC)
    for i, ticker in enumerate(DEFAULT_WATCHLIST):
        added_at = (base + timedelta(microseconds=i)).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, ticker, added_at) VALUES (?, ?, ?)",
            (user_id, ticker, added_at),
        )


def init_db(db_path: str | None = None) -> None:
    """Create the schema and seed default data if needed. Idempotent.

    Sets the module-level DB path used by every subsequent call. Seeding happens
    only when the default user profile is missing (i.e. a fresh database), so a
    user who empties their watchlist does not get it re-seeded on restart.
    """
    global _db_path
    with _init_lock:
        path = db_path or os.environ.get("DB_PATH") or str(DEFAULT_DB_PATH)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _db_path = path

        conn = connect(path)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA_SQL)
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT 1 FROM users_profile WHERE id = ?", (DEFAULT_USER_ID,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                        (DEFAULT_USER_ID, DEFAULT_CASH, now_iso()),
                    )
                    seed_default_watchlist(conn)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")
        finally:
            conn.close()
