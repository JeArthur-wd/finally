"""Process-wide singletons: the shared price cache and the active market data source.

Other modules read these attributes at call time (``state.price_cache``), so tests
can swap them with :func:`configure` or ``monkeypatch.setattr``.
"""

from __future__ import annotations

from app.market import MarketDataSource, PriceCache

price_cache: PriceCache = PriceCache()
market_source: MarketDataSource | None = None


def configure(
    cache: PriceCache | None = None,
    source: MarketDataSource | None = None,
) -> None:
    """Replace the singletons (used by app startup and tests)."""
    global price_cache, market_source
    if cache is not None:
        price_cache = cache
    market_source = source
