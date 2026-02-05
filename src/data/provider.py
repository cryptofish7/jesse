"""Abstract base class for data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime

from src.core.types import Candle


class DataProvider(ABC):
    """Base interface for all data providers (historical and live)."""

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch historical OHLCV + OI + CVD data."""

    @abstractmethod
    async def subscribe(
        self,
        symbol: str,
        timeframes: list[str],
        callback: Callable[[str, Candle], Awaitable[None]],
    ) -> None:
        """Subscribe to live candle updates."""

    @abstractmethod
    async def unsubscribe(self) -> None:
        """Clean up subscriptions."""
