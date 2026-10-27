"""Portfolio REST endpoints: valuation, trading, and value history."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import services

from .errors import error_response

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    """Body of POST /api/portfolio/trade."""

    ticker: str
    quantity: float
    side: str


@router.get("")
def get_portfolio() -> dict:
    """Current positions, cash balance, total value and unrealized P&L."""
    return services.get_portfolio()


@router.post("/trade", response_model=None)
async def trade(body: TradeRequest) -> dict | JSONResponse:
    """Execute a market order and return the trade plus the updated portfolio."""
    try:
        trade_record = await services.execute_trade(body.ticker, body.side, body.quantity)
    except services.TradeError as exc:
        return error_response(str(exc), 400)
    return {"trade": trade_record, "portfolio": services.get_portfolio()}


@router.get("/history")
def history() -> list[dict]:
    """Portfolio value snapshots (oldest first, at most 1000)."""
    return services.get_history(1000)
