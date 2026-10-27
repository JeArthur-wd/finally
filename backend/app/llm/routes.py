"""Chat API routes: POST /api/chat and GET /api/chat/history."""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import service

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_LIMIT = 50


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@router.post("")
async def post_chat(request: Request):
    """Send a chat message; returns ChatResponse ``{message, actions}``."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return _error("Request body must be JSON: {\"message\": \"...\"}")
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        return _error("Message must not be empty")
    return await service.handle_chat(message.strip())


@router.get("/history")
async def get_chat_history():
    """Return the last 50 chat messages, oldest first."""
    return service.get_history(HISTORY_LIMIT)
