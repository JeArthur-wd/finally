"""LLM client: LiteLLM -> OpenRouter -> Cerebras, with structured outputs.

Follows the cerebras-inference skill. ``litellm`` is imported lazily because it is
slow to import and is not needed in mock mode or when no API key is configured.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from pydantic import ValidationError

from .models import LLMResponse, LLMTrade, LLMWatchlistChange

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
TIMEOUT_SECONDS = 30.0


class LLMError(Exception):
    """Raised for any LLM failure. The message is short and safe to show to users."""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json_text(content: str) -> str:
    """Strip markdown fences and surrounding prose, returning the outermost JSON object."""
    text = _FENCE_RE.sub("", content.strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def parse_llm_output(content: str | None) -> LLMResponse:
    """Parse the raw LLM output into an LLMResponse.

    Strict validation first; on failure, a lenient pass that tolerates code fences,
    missing action arrays (treated as empty) and drops individually-invalid actions.
    Raises LLMError if no usable ``message`` can be recovered.
    """
    if not content or not content.strip():
        raise LLMError("empty response from AI service")

    try:
        return LLMResponse.model_validate_json(content)
    except ValidationError:
        pass

    try:
        data = json.loads(_extract_json_text(content))
    except json.JSONDecodeError as exc:
        raise LLMError("AI service returned malformed JSON") from exc

    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        raise LLMError("AI service response was missing a message")

    trades: list[LLMTrade] = []
    for item in data.get("trades") or []:
        try:
            trades.append(LLMTrade.model_validate(item))
        except ValidationError:
            logger.warning("Dropping invalid trade from LLM output: %r", item)

    changes: list[LLMWatchlistChange] = []
    for item in data.get("watchlist_changes") or []:
        try:
            changes.append(LLMWatchlistChange.model_validate(item))
        except ValidationError:
            logger.warning("Dropping invalid watchlist change from LLM output: %r", item)

    return LLMResponse(message=data["message"], trades=trades, watchlist_changes=changes)


def _call_sync(messages: list[dict[str, str]]) -> str | None:
    import litellm

    response = litellm.completion(
        model=MODEL,
        messages=messages,
        response_format=LLMResponse,
        reasoning_effort="low",
        extra_body=EXTRA_BODY,
        timeout=TIMEOUT_SECONDS,
    )
    return response.choices[0].message.content


async def call_llm(messages: list[dict[str, str]]) -> LLMResponse:
    """Call the LLM and return a parsed structured response. Raises LLMError on any failure."""
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        raise LLMError("the AI service is not configured — OPENROUTER_API_KEY is missing")

    try:
        content = await asyncio.wait_for(
            asyncio.to_thread(_call_sync, messages), timeout=TIMEOUT_SECONDS + 1
        )
    except TimeoutError as exc:
        raise LLMError("the request timed out") from exc
    except Exception as exc:  # any provider/network error degrades gracefully
        logger.exception("LLM call failed")
        if "timeout" in type(exc).__name__.lower():
            raise LLMError("the request timed out") from exc
        raise LLMError(f"{type(exc).__name__}") from exc

    return parse_llm_output(content)
