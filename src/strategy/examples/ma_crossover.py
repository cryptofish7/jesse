"""Moving average crossover strategy — example implementation."""

from __future__ import annotations

from typing import Any

from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Signal
from src.strategy.base import Strategy


def _sma(candles: list[Candle], period: int) -> float | None:
    """Calculate simple moving average of close prices over the last `period` candles."""
    if len(candles) < period:
        return None
    return sum(c.close for c in candles[-period:]) / period


class MACrossover(Strategy):
    """Simple moving average crossover strategy.

    Opens a long when the fast MA crosses above the slow MA.
    Opens a short when the fast MA crosses below the slow MA.
    Closes any existing position on the opposite signal.

    Parameters:
        fast_period: Number of candles for the fast MA (default: 10).
        slow_period: Number of candles for the slow MA (default: 30).
        risk_percent: Position size as % of equity (default: 1.0 = 100%).
        sl_percent: Stop loss distance as % of entry price (default: 2.0).
        tp_percent: Take profit distance as % of entry price (default: 4.0).
    """

    timeframes = ["1m"]

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        risk_percent: float = 1.0,
        sl_percent: float = 2.0,
        tp_percent: float = 4.0,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.risk_percent = risk_percent
        self.sl_percent = sl_percent
        self.tp_percent = tp_percent
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_candle(
        self,
        data: MultiTimeframeData,
        portfolio: Portfolio,
    ) -> list[Signal]:
        candles = data["1m"].history
        price = data["1m"].latest.close

        fast_ma = _sma(candles, self.fast_period)
        slow_ma = _sma(candles, self.slow_period)

        if fast_ma is None or slow_ma is None:
            return []

        signals: list[Signal] = []

        # Detect crossover (need previous values)
        if self._prev_fast is not None and self._prev_slow is not None:
            crossed_above = self._prev_fast <= self._prev_slow and fast_ma > slow_ma
            crossed_below = self._prev_fast >= self._prev_slow and fast_ma < slow_ma

            if crossed_above:
                # Close any short positions, open long
                for pos in portfolio.positions:
                    if pos.side == "short":
                        signals.append(Signal.close(position_id=pos.id))
                signals.append(
                    Signal.open_long(
                        size_percent=self.risk_percent,
                        stop_loss=price * (1 - self.sl_percent / 100),
                        take_profit=price * (1 + self.tp_percent / 100),
                    )
                )

            elif crossed_below:
                # Close any long positions, open short
                for pos in portfolio.positions:
                    if pos.side == "long":
                        signals.append(Signal.close(position_id=pos.id))
                signals.append(
                    Signal.open_short(
                        size_percent=self.risk_percent,
                        stop_loss=price * (1 + self.sl_percent / 100),
                        take_profit=price * (1 - self.tp_percent / 100),
                    )
                )

        self._prev_fast = fast_ma
        self._prev_slow = slow_ma
        return signals

    def get_state(self) -> dict[str, Any]:
        return {
            "prev_fast": self._prev_fast,
            "prev_slow": self._prev_slow,
        }

    def set_state(self, state: dict[str, Any]) -> None:
        self._prev_fast = state.get("prev_fast")
        self._prev_slow = state.get("prev_slow")
