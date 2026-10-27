"""Chat flow against the real app.db + app.services (temp DB, fake market source)."""

from app import db
from app.llm.service import handle_chat
from tests.services.conftest import env  # noqa: F401  (re-exported fixture)


async def test_mock_chat_end_to_end(env, mock_mode):  # noqa: F811
    resp = await handle_chat("buy 2 AAPL")
    assert resp["actions"][0]["status"] == "executed"
    assert resp["actions"][0]["price"] == 190.0
    assert db.get_position("AAPL")["quantity"] == 2

    resp = await handle_chat("buy 100000 AAPL")
    assert resp["actions"][0]["status"] == "failed"
    assert "⚠️ Could not buy 100000 AAPL: Insufficient cash" in resp["message"]["content"]

    resp = await handle_chat("add PYPL")
    assert resp["actions"][0]["status"] == "executed"
    assert "PYPL" in db.get_watchlist()

    resp = await handle_chat("remove ZZZZ")
    assert resp["actions"][0]["status"] == "failed"

    history = db.get_chat_messages(50)
    assert len(history) == 8
    assert history[1]["actions"][0]["type"] == "trade"
    assert history[3]["actions"][0]["status"] == "failed"
    assert history[0]["actions"] is None
