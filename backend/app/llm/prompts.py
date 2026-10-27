"""System prompt and message construction for the FinAlly chat assistant."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant inside a simulated trading workstation.
The user trades a virtual portfolio with fake money; market orders fill instantly at the current price.

Your job:
- Analyze portfolio composition, risk concentration and P&L.
- Suggest trades with brief reasoning.
- Execute trades when the user asks for them or agrees to your suggestion.
- Manage the watchlist proactively (add tickers the user is discussing, remove ones they no longer care about).
- Be concise and data-driven. Use numbers from the portfolio context below.

Rules for actions:
- Quantities are ALWAYS in shares. If the user gives a dollar amount, convert it using the
  current price from the context and round DOWN to 4 decimal places.
- Only buy if cash is sufficient; only sell shares the user actually holds.
- Tickers are uppercase symbols such as AAPL.
- Only include trades/watchlist changes you actually intend to execute now. Do not include
  trades the user has not asked for or agreed to.

Always respond with valid JSON matching this schema (every field required, arrays may be empty):
{"message": "<your reply to the user>",
 "trades": [{"ticker": "AAPL", "side": "buy" | "sell", "quantity": 10}],
 "watchlist_changes": [{"ticker": "PYPL", "action": "add" | "remove"}]}
"""


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def build_portfolio_context(portfolio: dict | None, watchlist: list[dict] | None) -> str:
    """Render the portfolio and watchlist as compact text for the LLM."""
    lines: list[str] = ["# Current portfolio"]
    if portfolio:
        lines.append(f"Cash: {_money(portfolio.get('cash_balance'))}")
        lines.append(f"Total value: {_money(portfolio.get('total_value'))}")
        lines.append(f"Positions value: {_money(portfolio.get('positions_value'))}")
        lines.append(f"Unrealized P&L: {_money(portfolio.get('unrealized_pnl'))}")
        positions = portfolio.get("positions") or []
        if positions:
            lines.append("Positions:")
            for p in positions:
                lines.append(
                    f"- {p.get('ticker')}: {p.get('quantity')} sh, avg cost {_money(p.get('avg_cost'))}, "
                    f"price {_money(p.get('current_price'))}, value {_money(p.get('market_value'))}, "
                    f"P&L {_money(p.get('unrealized_pnl'))} ({_pct(p.get('unrealized_pnl_pct'))})"
                )
        else:
            lines.append("Positions: none")
    else:
        lines.append("(portfolio unavailable)")

    lines.append("")
    lines.append("# Watchlist (change % since session open)")
    if watchlist:
        for w in watchlist:
            price = w.get("price")
            price_str = _money(price) if price is not None else "no price yet"
            lines.append(f"- {w.get('ticker')}: {price_str} ({_pct(w.get('change_percent'))})")
    else:
        lines.append("(empty)")
    return "\n".join(lines)


def _history_content(msg: dict) -> str:
    """Return message content, with a short action summary for assistant messages."""
    content = str(msg.get("content") or "")
    actions = msg.get("actions")
    if msg.get("role") == "assistant" and isinstance(actions, list) and actions:
        parts = []
        for a in actions:
            if not isinstance(a, dict):
                continue
            if a.get("type") == "trade":
                parts.append(f"{a.get('side')} {a.get('quantity')} {a.get('ticker')}: {a.get('status')}")
            elif a.get("type") == "watchlist":
                parts.append(f"{a.get('action')} {a.get('ticker')}: {a.get('status')}")
        if parts:
            content += "\n[actions: " + "; ".join(parts) + "]"
    return content


def build_messages(
    user_message: str,
    history: list[dict] | None,
    portfolio: dict | None,
    watchlist: list[dict] | None,
) -> list[dict[str, str]]:
    """Build the full message list: system prompt + context, history, new user message."""
    system = SYSTEM_PROMPT + "\n\n" + build_portfolio_context(portfolio, watchlist)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for msg in history or []:
        role = msg.get("role")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": _history_content(msg)})
    messages.append({"role": "user", "content": user_message})
    return messages
