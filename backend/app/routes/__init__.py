"""REST routers for portfolio, watchlist and system endpoints."""

from .errors import error_response, install_error_handlers
from .portfolio import router as portfolio_router
from .system import router as system_router
from .watchlist import router as watchlist_router

__all__ = [
    "error_response",
    "install_error_handlers",
    "portfolio_router",
    "system_router",
    "watchlist_router",
]
