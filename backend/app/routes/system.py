"""System endpoints: health check and state reset."""

from __future__ import annotations

from fastapi import APIRouter

from app import services

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


@router.post("/reset")
async def reset() -> dict:
    """Restore cash, positions, watchlist and history to defaults; return the fresh Portfolio."""
    await services.reset()
    return services.get_portfolio()
