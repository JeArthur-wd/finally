"""Pydantic models for the LLM structured-output schema (contract §6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LLMTrade(BaseModel):
    """A trade the LLM wants executed. Quantity is always in shares."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class LLMWatchlistChange(BaseModel):
    """A watchlist modification the LLM wants applied."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: Literal["add", "remove"]


class LLMResponse(BaseModel):
    """Complete structured LLM output. Every field is required; arrays may be empty."""

    model_config = ConfigDict(extra="forbid")

    message: str
    trades: list[LLMTrade]
    watchlist_changes: list[LLMWatchlistChange]
