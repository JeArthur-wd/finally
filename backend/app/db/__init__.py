"""Database layer for FinAlly (SQLite via stdlib sqlite3).

Public API:
    init_db, get_db_path, transaction
    get_cash, set_cash
    get_watchlist, get_watchlist_items, add_watchlist_ticker, remove_watchlist_ticker
    get_positions, get_position, upsert_position, delete_position
    insert_trade
    insert_snapshot, get_snapshots
    insert_chat_message, get_chat_messages
    reset_user
"""

from .connection import get_db_path, init_db, transaction
from .repository import (
    add_watchlist_ticker,
    delete_position,
    get_cash,
    get_chat_messages,
    get_position,
    get_positions,
    get_snapshots,
    get_watchlist,
    get_watchlist_items,
    insert_chat_message,
    insert_snapshot,
    insert_trade,
    remove_watchlist_ticker,
    reset_user,
    set_cash,
    upsert_position,
)
from .schema import DEFAULT_CASH, DEFAULT_USER_ID, DEFAULT_WATCHLIST

__all__ = [
    "DEFAULT_CASH",
    "DEFAULT_USER_ID",
    "DEFAULT_WATCHLIST",
    "init_db",
    "get_db_path",
    "transaction",
    "get_cash",
    "set_cash",
    "get_watchlist",
    "get_watchlist_items",
    "add_watchlist_ticker",
    "remove_watchlist_ticker",
    "get_positions",
    "get_position",
    "upsert_position",
    "delete_position",
    "insert_trade",
    "insert_snapshot",
    "get_snapshots",
    "insert_chat_message",
    "get_chat_messages",
    "reset_user",
]
