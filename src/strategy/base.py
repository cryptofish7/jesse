"""Strategy base class — all user strategies inherit from this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.core.portfolio import Portfolio
from src.core.types import MultiTimeframeData, Signal


class Strategy(ABC):
    """Base class for trading strategies.

    Subclasses must:
    - Set `timeframes` to declare which timeframes they need.
    - Implement `on_candle()` to return trading signals.
    """

    timeframes: list[str] = ["1m"]

    @abstractmethod
    def on_candle(
        self,
        data: MultiTimeframeData,
        portfolio: Portfolio,
    ) -> list[Signal]:
        """Called on each candle close of the lowest declared timeframe.

        Returns a list of signals (can be empty).
        """

    def on_init(self, data: MultiTimeframeData) -> None:  # noqa: B027
        """Optional: called once with historical data before the main loop."""

    def get_state(self) -> dict[str, Any]:
        """Return serializable state for persistence/crash recovery."""
        return {}

    def set_state(self, state: dict[str, Any]) -> None:  # noqa: B027
        """Restore state from a previously saved dict."""
