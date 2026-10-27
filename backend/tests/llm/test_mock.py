"""Tests for the deterministic mock LLM rules."""

import pytest

from app.llm.mock import MOCK_DEFAULT_MESSAGE, is_mock_enabled, mock_response


def test_buy_rule():
    r = mock_response("buy 5 AAPL")
    assert r.message == "Buying 5 shares of AAPL."
    assert [(t.ticker, t.side, t.quantity) for t in r.trades] == [("AAPL", "buy", 5.0)]
    assert r.watchlist_changes == []


def test_sell_rule():
    r = mock_response("sell 3 msft")
    assert r.message == "Selling 3 shares of MSFT."
    assert [(t.ticker, t.side, t.quantity) for t in r.trades] == [("MSFT", "sell", 3.0)]


@pytest.mark.parametrize("text", ["add PYPL", "watch pypl", "please ADD pypl now"])
def test_add_rule(text):
    r = mock_response(text)
    assert r.message == "Adding PYPL to your watchlist."
    assert [(c.ticker, c.action) for c in r.watchlist_changes] == [("PYPL", "add")]
    assert r.trades == []


def test_remove_rule():
    r = mock_response("Remove tsla")
    assert r.message == "Removing TSLA from your watchlist."
    assert [(c.ticker, c.action) for c in r.watchlist_changes] == [("TSLA", "remove")]


@pytest.mark.parametrize("text", ["hello", "what is my portfolio?", "buy AAPL", "", "buy -5 AAPL x"])
def test_default_rule(text):
    r = mock_response(text)
    assert r.message == MOCK_DEFAULT_MESSAGE
    assert r.trades == [] and r.watchlist_changes == []


def test_case_insensitive_and_embedded():
    r = mock_response("Hey, BUY 10 nvda please")
    assert r.message == "Buying 10 shares of NVDA."
    assert r.trades[0].ticker == "NVDA"


def test_decimal_quantity():
    r = mock_response("buy 2.5 AAPL")
    assert r.message == "Buying 2.5 shares of AAPL."
    assert r.trades[0].quantity == 2.5
    assert mock_response("sell 0.125 brk.b").trades[0].ticker == "BRK.B"


def test_large_quantity_kept():
    r = mock_response("buy 100000 AAPL")
    assert r.trades[0].quantity == 100000
    assert r.message == "Buying 100000 shares of AAPL."


def test_is_mock_enabled(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "TRUE")
    assert is_mock_enabled()
    monkeypatch.setenv("LLM_MOCK", "false")
    assert not is_mock_enabled()
    monkeypatch.delenv("LLM_MOCK")
    assert not is_mock_enabled()
