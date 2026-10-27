"""Shared test doubles for service and API tests."""

from __future__ import annotations

from app.market import MarketDataSource, PriceCache


class FakeMarketSource(MarketDataSource):
    """In-memory market source. Tickers listed in `auto_prices` get a price on add."""

    def __init__(self, cache: PriceCache, auto_prices: dict[str, float] | None = None) -> None:
        self.cache = cache
        self.auto_prices = auto_prices or {}
        self.tickers: list[str] = []
        self.added: list[str] = []
        self.removed: list[str] = []
        self.started = False
        self.stopped = False

    async def start(self, tickers: list[str]) -> None:
        self.started = True
        for t in tickers:
            await self.add_ticker(t)

    async def stop(self) -> None:
        self.stopped = True

    async def add_ticker(self, ticker: str) -> None:
        self.added.append(ticker)
        if ticker not in self.tickers:
            self.tickers.append(ticker)
        if ticker in self.auto_prices and ticker not in self.cache:
            self.cache.update(ticker, self.auto_prices[ticker])

    async def remove_ticker(self, ticker: str) -> None:
        self.removed.append(ticker)
        if ticker in self.tickers:
            self.tickers.remove(ticker)
        self.cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self.tickers)
