"""Chat service: persist, call LLM (or mock), auto-execute actions, persist, respond.

``app.db`` and ``app.services`` are resolved lazily via ``importlib`` so this module can be
imported (and unit-tested with fakes in ``sys.modules``) independently of them.
"""

from __future__ import annotations

import importlib
import logging
import uuid
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from .client import LLMError, call_llm
from .mock import is_mock_enabled, mock_response
from .models import LLMResponse
from .prompts import build_messages

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
FAILURE_TEMPLATE = (
    "Sorry — I couldn't reach the AI service right now ({reason}). Please try again."
)


def _db() -> ModuleType:
    return importlib.import_module("app.db")


def _services() -> ModuleType:
    return importlib.import_module("app.services")


def _fmt_qty(quantity: float) -> str:
    return f"{quantity:g}"


def _error_text(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


async def _execute_watchlist_change(services: ModuleType, ticker: str, action: str) -> dict:
    result: dict[str, Any] = {"type": "watchlist", "ticker": ticker.strip().upper(), "action": action}
    try:
        if action == "add":
            item = await services.add_ticker(ticker)
            if isinstance(item, dict) and item.get("ticker"):
                result["ticker"] = item["ticker"]
        else:
            await services.remove_ticker(ticker)
        result["status"] = "executed"
    except services.WatchlistError as exc:
        result.update(status="failed", error=_error_text(exc))
    except Exception as exc:  # unexpected: report as a failed action, never raise
        logger.exception("Unexpected error applying watchlist change")
        result.update(status="failed", error=f"Unexpected error: {_error_text(exc)}")
    return result


async def _execute_trade(services: ModuleType, ticker: str, side: str, quantity: float) -> dict:
    result: dict[str, Any] = {
        "type": "trade",
        "ticker": ticker.strip().upper(),
        "side": side,
        "quantity": quantity,
        "price": None,
    }
    try:
        trade = await services.execute_trade(ticker, side, quantity)
        result.update(
            ticker=trade.get("ticker", result["ticker"]),
            quantity=trade.get("quantity", quantity),
            price=trade.get("price"),
            status="executed",
        )
    except services.TradeError as exc:
        result.update(status="failed", error=_error_text(exc))
    except Exception as exc:  # unexpected: report as a failed action, never raise
        logger.exception("Unexpected error executing trade")
        result.update(status="failed", error=f"Unexpected error: {_error_text(exc)}")
    return result


def _failure_line(action: dict) -> str:
    if action["type"] == "trade":
        what = f"{action['side']} {_fmt_qty(action['quantity'])} {action['ticker']}"
    elif action["action"] == "add":
        what = f"add {action['ticker']} to your watchlist"
    else:
        what = f"remove {action['ticker']} from your watchlist"
    return f"⚠️ Could not {what}: {action.get('error', 'unknown error')}"


async def execute_actions(llm: LLMResponse) -> list[dict]:
    """Apply watchlist changes first, then trades. Each failure is captured, never raised."""
    if not llm.watchlist_changes and not llm.trades:
        return []
    services = _services()
    actions: list[dict] = []
    for change in llm.watchlist_changes:
        actions.append(await _execute_watchlist_change(services, change.ticker, change.action))
    for trade in llm.trades:
        actions.append(await _execute_trade(services, trade.ticker, trade.side, trade.quantity))
    return actions


def _load_context() -> tuple[list[dict], dict | None, list[dict] | None]:
    history: list[dict] = []
    portfolio: dict | None = None
    watchlist: list[dict] | None = None
    try:
        history = _db().get_chat_messages(HISTORY_LIMIT)
    except Exception:
        logger.exception("Failed to load chat history")
    try:
        services = _services()
        portfolio = services.get_portfolio()
        watchlist = services.get_watchlist()
    except Exception:
        logger.exception("Failed to load portfolio context")
    return history, portfolio, watchlist


def _save(role: str, content: str, actions: list[dict] | None) -> dict:
    """Persist a chat message; on DB failure, log and return a synthesized row."""
    try:
        row = dict(_db().insert_chat_message(role, content, actions))
    except Exception:
        logger.exception("Failed to persist %s chat message", role)
        row = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "created_at": datetime.now(UTC).isoformat(),
        }
    row["role"] = role
    row["content"] = content
    row["actions"] = actions
    return row


async def handle_chat(message: str) -> dict:
    """Process one user chat message and return a ChatResponse dict. Never raises."""
    history, portfolio, watchlist = _load_context()
    _save("user", message, None)

    actions: list[dict] = []
    try:
        if is_mock_enabled():
            llm = mock_response(message)
        else:
            llm = await call_llm(build_messages(message, history, portfolio, watchlist))
    except LLMError as exc:
        content = FAILURE_TEMPLATE.format(reason=str(exc))
    except Exception as exc:
        logger.exception("Unexpected LLM failure")
        content = FAILURE_TEMPLATE.format(reason=type(exc).__name__)
    else:
        actions = await execute_actions(llm)
        content = llm.message
        failures = [_failure_line(a) for a in actions if a.get("status") == "failed"]
        if failures:
            content = (content.rstrip() + "\n\n" + "\n".join(failures)).lstrip()

    assistant = _save("assistant", content, actions)
    return {"message": assistant, "actions": actions}


def get_history(limit: int = 50) -> list[dict]:
    """Return the most recent ``limit`` chat messages, oldest first."""
    return _db().get_chat_messages(limit)
