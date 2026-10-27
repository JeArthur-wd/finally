"""Tests for structured-output parsing, prompt building and the LLM client."""

import json

import pytest

from app.llm.client import EXTRA_BODY, MODEL, LLMError, call_llm, parse_llm_output
from app.llm.models import LLMResponse
from app.llm.prompts import build_messages


def test_parse_valid_full():
    raw = json.dumps({
        "message": "Done.",
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
    })
    r = parse_llm_output(raw)
    assert r.message == "Done."
    assert r.trades[0].quantity == 10 and r.trades[0].side == "buy"
    assert r.watchlist_changes[0].action == "add"


def test_parse_valid_empty_arrays():
    r = parse_llm_output('{"message": "hi", "trades": [], "watchlist_changes": []}')
    assert r.message == "hi" and r.trades == [] and r.watchlist_changes == []


def test_parse_missing_arrays_defaults_to_empty():
    r = parse_llm_output('{"message": "hi"}')
    assert r.trades == [] and r.watchlist_changes == []


def test_parse_code_fenced_with_prose():
    raw = 'Sure!\n```json\n{"message": "ok", "trades": [], "watchlist_changes": []}\n```'
    assert parse_llm_output(raw).message == "ok"


def test_parse_drops_invalid_items():
    raw = json.dumps({
        "message": "m",
        "trades": [{"ticker": "AAPL", "side": "hold", "quantity": 1},
                   {"ticker": "MSFT", "side": "sell", "quantity": 2}],
        "watchlist_changes": [{"ticker": "X"}],
    })
    r = parse_llm_output(raw)
    assert [t.ticker for t in r.trades] == ["MSFT"]
    assert r.watchlist_changes == []


@pytest.mark.parametrize("raw", [None, "", "   ", "not json at all", "{broken", "[1, 2]",
                                 '{"trades": []}', '{"message": 5}'])
def test_parse_malformed_raises(raw):
    with pytest.raises(LLMError):
        parse_llm_output(raw)


def test_schema_all_fields_required_and_strict():
    schema = LLMResponse.model_json_schema()
    assert set(schema["required"]) == {"message", "trades", "watchlist_changes"}
    assert schema["additionalProperties"] is False


def test_build_messages_includes_context_and_history():
    history = [
        {"role": "user", "content": "buy 1 AAPL", "actions": None},
        {"role": "assistant", "content": "Bought.",
         "actions": [{"type": "trade", "ticker": "AAPL", "side": "buy", "quantity": 1,
                      "price": 190.0, "status": "executed"}]},
    ]
    portfolio = {"cash_balance": 9810.0, "total_value": 10000.0, "positions_value": 190.0,
                 "unrealized_pnl": 0.0,
                 "positions": [{"ticker": "AAPL", "quantity": 1, "avg_cost": 190.0,
                                "current_price": 190.0, "market_value": 190.0,
                                "unrealized_pnl": 0.0, "unrealized_pnl_pct": 0.0}]}
    watchlist = [{"ticker": "AAPL", "price": 190.0, "change_percent": 1.25},
                 {"ticker": "PYPL", "price": None, "change_percent": None}]
    msgs = build_messages("how am I doing?", history, portfolio, watchlist)
    assert msgs[0]["role"] == "system"
    sys_text = msgs[0]["content"]
    assert "FinAlly, an AI trading assistant" in sys_text
    assert "$9,810.00" in sys_text and "+1.25%" in sys_text and "no price yet" in sys_text
    assert "always in shares" in sys_text.lower()
    assert [m["role"] for m in msgs[1:]] == ["user", "assistant", "user"]
    assert "[actions: buy 1 AAPL: executed]" in msgs[2]["content"]
    assert msgs[-1]["content"] == "how am I doing?"


async def test_call_llm_missing_key(monkeypatch, fake_completion):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        await call_llm([{"role": "user", "content": "hi"}])
    assert fake_completion.calls == []


async def test_call_llm_uses_cerebras_structured_outputs(real_mode, fake_completion):
    fake_completion.content = '{"message": "hi", "trades": [], "watchlist_changes": []}'
    r = await call_llm([{"role": "user", "content": "hi"}])
    assert r.message == "hi"
    kw = fake_completion.calls[0]
    assert kw["model"] == MODEL == "openrouter/openai/gpt-oss-120b"
    assert kw["extra_body"] == EXTRA_BODY
    assert kw["response_format"] is LLMResponse
    assert kw["timeout"] == 30.0


async def test_call_llm_provider_error(real_mode, fake_completion):
    fake_completion.exc = RuntimeError("boom")
    with pytest.raises(LLMError):
        await call_llm([{"role": "user", "content": "hi"}])


async def test_call_llm_timeout_error(real_mode, fake_completion):
    class APITimeoutError(Exception):
        pass

    fake_completion.exc = APITimeoutError("slow")
    with pytest.raises(LLMError, match="timed out"):
        await call_llm([{"role": "user", "content": "hi"}])
