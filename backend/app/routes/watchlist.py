"""Watchlist REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import services

from .errors import error_response

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTickerRequest(BaseModel):
    """Body of POST /api/watchlist."""

    ticker: str


@router.get("")
def list_watchlist() -> list[dict]:
    """Watchlist tickers with latest prices, ordered by added_at."""
    return services.get_watchlist()


@router.post("", response_model=None)
async def add(body: AddTickerRequest) -> JSONResponse:
    """Add a ticker: 201 if new, 200 if it was already present."""
    try:
        item, created = await services.add_ticker_with_status(body.ticker)
    except services.WatchlistError as exc:
        return error_response(str(exc), 400)
    return JSONResponse(item, status_code=201 if created else 200)


@router.delete("/{ticker}", response_model=None)
async def remove(ticker: str) -> dict | JSONResponse:
    """Remove a ticker (404 if it isn't on the watchlist)."""
    try:
        await services.remove_ticker(ticker)
    except services.WatchlistNotFoundError as exc:
        return error_response(str(exc), 404)
    except services.WatchlistError as exc:
        return error_response(str(exc), 400)
    return {"ticker": ticker.strip().upper()}
