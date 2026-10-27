"""Tests for the chat service flow and the chat router."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm import router
from app.llm.service import handle_chat


@pytest.fixture
def client(fake_db, fake_services):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# --- mock mode flow ---------------------------------------------------------

async def test_mock_buy_executes_and_persists(mock_mode, fake_db, fake_services):
    resp = await handle_chat("buy 2 AAPL")
    assert resp["actions"] == [{"type": "trade", "ticker": "AAPL", "side": "buy", "quantity": 2,
                                "price": 190.0, "status": "executed"}]
    msg = resp["message"]
    assert msg["role"] == "assistant"
    assert msg["content"] == "Buying 2 shares of AAPL."
    assert msg["actions"] == resp["actions"]
    assert {"id", "created_at"} <= msg.keys()
    # persistence: user message (no actions) then assistant message (with actions)
    assert [(m["role"], m["content"]) for m in fake_db.messages] == [
        ("user", "buy 2 AAPL"), ("assistant", "Buying 2 shares of AAPL.")]
    assert fake_db.messages[0]["actions"] is None
    assert fake_db.messages[1]["actions"] == resp["actions"]
    assert fake_services.holdings["AAPL"] == 2


async def test_mock_failed_trade_appends_warning(mock_mode, fake_db, fake_services):
    resp = await handle_chat("buy 100000 AAPL")
    (action,) = resp["actions"]
    assert action["status"] == "failed"
    assert action["price"] is None
    assert action["error"].startswith("Insufficient cash")
    content = resp["message"]["content"]
    assert content.startswith("Buying 100000 shares of AAPL.\n\n")
    assert "⚠️ Could not buy 100000 AAPL: Insufficient cash" in content
    assert fake_db.messages[-1]["content"] == content
    assert fake_db.messages[-1]["actions"][0]["status"] == "failed"


async def test_mock_watchlist_add_and_remove_failure(mock_mode, fake_db, fake_services):
    resp = await handle_chat("add pypl")
    assert resp["actions"] == [{"type": "watchlist", "ticker": "PYPL", "action": "add",
                                "status": "executed"}]
    resp = await handle_chat("remove ZZZ")
    (action,) = resp["actions"]
    assert action["status"] == "failed" and "not on the watchlist" in action["error"]
    assert "⚠️ Could not remove ZZZ from your watchlist" in resp["message"]["content"]


async def test_mock_default_no_actions(mock_mode, fake_db, fake_services):
    resp = await handle_chat("hello")
    assert resp["actions"] == []
    assert "mock mode" in resp["message"]["content"]
    assert fake_services.calls == []


# --- real LLM path (litellm mocked) ----------------------------------------

async def test_real_mixed_actions_order_and_statuses(real_mode, fake_db, fake_services,
                                                     fake_completion):
    fake_completion.content = json.dumps({
        "message": "Rebalancing.",
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1},
                   {"ticker": "MSFT", "side": "sell", "quantity": 5}],
        "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
    })
    resp = await handle_chat("rebalance please")
    # watchlist changes run before trades
    assert [c[0] for c in fake_services.calls] == ["add", "trade", "trade"]
    statuses = [(a["type"], a["ticker"], a["status"]) for a in resp["actions"]]
    assert statuses == [("watchlist", "PYPL", "executed"), ("trade", "AAPL", "executed"),
                        ("trade", "MSFT", "failed")]
    content = resp["message"]["content"]
    assert content.startswith("Rebalancing.")
    assert "⚠️ Could not sell 5 MSFT: Insufficient shares: have 0, tried to sell 5" in content
    assert "Could not buy" not in content
    # prompt included context and the new message
    sent = fake_completion.calls[0]["messages"]
    assert sent[0]["role"] == "system" and "$1,000.00" in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "rebalance please"}


async def test_real_history_passed_without_duplicating_current(real_mode, fake_db,
                                                               fake_services, fake_completion):
    fake_completion.content = '{"message": "a", "trades": [], "watchlist_changes": []}'
    await handle_chat("first")
    await handle_chat("second")
    sent = fake_completion.calls[1]["messages"]
    assert [(m["role"], m["content"]) for m in sent[1:]] == [
        ("user", "first"), ("assistant", "a"), ("user", "second")]


async def test_history_limited_to_20(real_mode, fake_db, fake_services, fake_completion):
    for i in range(30):
        fake_db.insert_chat_message("user", f"m{i}")
    fake_completion.content = '{"message": "a", "trades": [], "watchlist_changes": []}'
    await handle_chat("new")
    sent = fake_completion.calls[0]["messages"]
    assert len(sent) == 1 + 20 + 1


async def test_missing_api_key_friendly(monkeypatch, fake_db, fake_services, fake_completion):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    resp = await handle_chat("buy 1 AAPL")
    assert resp["actions"] == []
    assert resp["message"]["content"].startswith("Sorry — I couldn't reach the AI service")
    assert "OPENROUTER_API_KEY" in resp["message"]["content"]
    assert fake_completion.calls == []
    assert fake_services.calls == []
    assert [m["role"] for m in fake_db.messages] == ["user", "assistant"]
    assert fake_db.messages[1]["actions"] == []


async def test_malformed_json_friendly(real_mode, fake_db, fake_services, fake_completion):
    fake_completion.content = "I am not JSON"
    resp = await handle_chat("hi")
    assert resp["actions"] == []
    assert "malformed JSON" in resp["message"]["content"]


async def test_unexpected_service_error_reported_not_raised(mock_mode, fake_db, fake_services):
    async def boom(*a, **k):
        raise RuntimeError("db exploded")

    fake_services.execute_trade = boom
    resp = await handle_chat("buy 1 AAPL")
    assert resp["actions"][0]["status"] == "failed"
    assert "db exploded" in resp["actions"][0]["error"]


async def test_db_failure_still_returns(mock_mode, fake_db, fake_services):
    def broken(*a, **k):
        raise RuntimeError("disk full")

    fake_db.insert_chat_message = broken
    fake_db.get_chat_messages = broken
    resp = await handle_chat("hello")
    assert resp["message"]["role"] == "assistant" and resp["message"]["id"]


# --- router -----------------------------------------------------------------

def test_post_chat_route(mock_mode, client, fake_db):
    r = client.post("/api/chat", json={"message": "buy 1 AAPL"})
    assert r.status_code == 200
    body = r.json()
    assert body["actions"][0]["status"] == "executed"
    assert body["message"]["role"] == "assistant"


@pytest.mark.parametrize("payload", [{"message": ""}, {"message": "   "}, {}, {"message": 5}, [1]])
def test_post_chat_rejects_empty(mock_mode, client, payload):
    r = client.post("/api/chat", json=payload)
    assert r.status_code == 400
    assert "error" in r.json()


def test_post_chat_rejects_non_json(mock_mode, client):
    r = client.post("/api/chat", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and "error" in r.json()


def test_history_route(mock_mode, client, fake_db):
    for i in range(60):
        fake_db.insert_chat_message("user", f"m{i}")
    r = client.get("/api/chat/history")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 50
    assert data[0]["content"] == "m10" and data[-1]["content"] == "m59"
