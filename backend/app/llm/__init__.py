"""LLM chat integration: structured-output client, mock, chat service and router."""

from .client import LLMError, call_llm, parse_llm_output
from .mock import mock_response
from .models import LLMResponse, LLMTrade, LLMWatchlistChange
from .routes import router
from .service import handle_chat

__all__ = [
    "LLMError",
    "LLMResponse",
    "LLMTrade",
    "LLMWatchlistChange",
    "call_llm",
    "handle_chat",
    "mock_response",
    "parse_llm_output",
    "router",
]
