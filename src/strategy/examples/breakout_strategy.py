"""Breakout strategy — example implementation.

Tracks the highest high and lowest low over a configurable lookback
period. Opens a long when price breaks above the upper channel, and
opens a short when price breaks below the lower channel. Positions
are managed with stop-loss and take-profit based on the channel width.

This is a classic Donchian channel breakout approach, commonly used
in trend-following systems.
"""

from __future__ import annotations

from typing import Any

from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Signal
from src.strategy.base import Strategy


def _channel(candles: list[Candle], period: int) -> tuple[float, float] | None:
    """Calculate the Donchian channel (highest high, lowest low) over the last ``period`` candles.

    Returns ``(upper, lower)`` or ``None`` if not enough data.
    """
    if len(candles) < period:
        return None
    window = candles[-period:]
    upper = max(c.high for c in window)
    lower = min(c.low for c in window)
    return upper, lower


class BreakoutStrategy(Strategy):
    """Donchian channel breakout strategy.

    Enters a long when the current close exceeds the highest high of
    the lookback period. Enters a short when the current close drops
    below the lowest low. Stop-loss is placed at the opposite channel
    boundary, and take-profit is set at a configurable multiple of the
    channel width from the entry price.

    Parameters:
        period: Lookback period for the channel (default: 20).
        risk_percent: Position size as fraction of equity (default: 1.0 = 100%).
        tp_multiplier: Take-profit distance as a multiple of channel width (default: 1.5).
    """

    timeframes = ["1m"]

    def __init__(
        self,
        period: int = 20,
        risk_percent: float = 1.0,
        tp_multiplier: float = 1.5,
    ) -> None:
        self.period = period
        self.risk_percent = risk_percent
        self.tp_multiplier = tp_multiplier
        self._prev_upper: float | None = None
        self._prev_lower: float | None = None

    def on_candle(
        self,
        data: MultiTimeframeData,
        portfolio: Portfolio,
    ) -> list[Signal]:
        candles = data["1m"].history
        price = data["1m"].latest.close

        result = _channel(candles, self.period)
        if result is None:
            return []

        upper, lower = result
        channel_width = upper - lower

        signals: list[Signal] = []

        # Need previous channel levels to detect breakouts
        if self._prev_upper is not None and self._prev_lower is not None and channel_width > 0:
            broke_above = price > self._prev_upper
            broke_below = price < self._prev_lower

            if broke_above:
                # Upside breakout -> close shorts, open long
                for pos in portfolio.positions:
                    if pos.side == "short":
                        signals.append(Signal.close(position_id=pos.id))
                signals.append(
                    Signal.open_long(
                        size_percent=self.risk_percent,
                        stop_loss=lower,
                        take_profit=price + channel_width * self.tp_multiplier,
                    )
                )

            elif broke_below:
                # Downside breakout -> close longs, open short
                for pos in portfolio.positions:
                    if pos.side == "long":
                        signals.append(Signal.close(position_id=pos.id))
                signals.append(
                    Signal.open_short(
                        size_percent=self.risk_percent,
                        stop_loss=upper,
                        take_profit=price - channel_width * self.tp_multiplier,
                    )
                )

        self._prev_upper = upper
        self._prev_lower = lower
        return signals

    def get_state(self) -> dict[str, Any]:
        """Return serializable state for crash recovery."""
        return {
            "prev_upper": self._prev_upper,
            "prev_lower": self._prev_lower,
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore state from a previously saved dict."""
        self._prev_upper = state.get("prev_upper")
        self._prev_lower = state.get("prev_lower")
