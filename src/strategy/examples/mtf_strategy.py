"""Multi-timeframe trend-following strategy — example implementation.

Demonstrates how to use multiple timeframes in Jesse. Uses the 4h
timeframe to determine the macro trend direction (via a simple moving
average) and the 1m timeframe for precise entries.

Entries are only taken in the direction of the 4h trend, and confirmed
by a short-term momentum condition on the 1m chart.
"""

from __future__ import annotations

from typing import Any

from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Signal
from src.strategy.base import Strategy


def _sma(candles: list[Candle], period: int) -> float | None:
    """Calculate simple moving average of close prices over the last ``period`` candles."""
    if len(candles) < period:
        return None
    return sum(c.close for c in candles[-period:]) / period


class MTFStrategy(Strategy):
    """Multi-timeframe trend-following strategy (4h + 1m).

    Uses the 4h chart to identify the macro trend direction via
    a simple moving average. When the 4h close is above its SMA,
    the trend is bullish; below, it is bearish.

    On the 1m chart, entries are confirmed by a short-term momentum
    condition: the fast SMA crossing above the slow SMA (for longs)
    or below (for shorts). Only signals that align with the 4h trend
    direction are taken.

    This demonstrates the core multi-timeframe pattern:
    - Declare both timeframes in ``timeframes``.
    - Access each via ``data['4h']`` and ``data['1m']``.
    - ``on_candle()`` fires on every 1m close; 4h data is always
      available (in-progress candle as ``latest``, completed candles
      in ``history``).

    Parameters:
        trend_period: SMA period for the 4h trend filter (default: 50).
        fast_period: Fast SMA period on 1m for entry timing (default: 10).
        slow_period: Slow SMA period on 1m for entry timing (default: 30).
        risk_percent: Position size as fraction of equity (default: 1.0 = 100%).
        sl_percent: Stop loss distance as % of entry price (default: 1.5).
        tp_percent: Take profit distance as % of entry price (default: 3.0).
    """

    timeframes = ["1m", "4h"]

    def __init__(
        self,
        trend_period: int = 50,
        fast_period: int = 10,
        slow_period: int = 30,
        risk_percent: float = 1.0,
        sl_percent: float = 1.5,
        tp_percent: float = 3.0,
    ) -> None:
        self.trend_period = trend_period
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
        # --- 4h trend filter ---
        candles_4h = data["4h"].history
        trend_sma = _sma(candles_4h, self.trend_period)
        if trend_sma is None:
            return []

        price_4h = data["4h"].latest.close
        trend_is_bullish = price_4h > trend_sma
        trend_is_bearish = price_4h < trend_sma

        # --- 1m entry timing ---
        candles_1m = data["1m"].history
        price_1m = data["1m"].latest.close

        fast_ma = _sma(candles_1m, self.fast_period)
        slow_ma = _sma(candles_1m, self.slow_period)

        if fast_ma is None or slow_ma is None:
            return []

        signals: list[Signal] = []

        if self._prev_fast is not None and self._prev_slow is not None:
            crossed_above = self._prev_fast <= self._prev_slow and fast_ma > slow_ma
            crossed_below = self._prev_fast >= self._prev_slow and fast_ma < slow_ma

            if crossed_above and trend_is_bullish:
                # 1m crossover aligns with 4h uptrend -> long
                for pos in portfolio.positions:
                    if pos.side == "short":
                        signals.append(Signal.close(position_id=pos.id))
                signals.append(
                    Signal.open_long(
                        size_percent=self.risk_percent,
                        stop_loss=price_1m * (1 - self.sl_percent / 100),
                        take_profit=price_1m * (1 + self.tp_percent / 100),
                    )
                )

            elif crossed_below and trend_is_bearish:
                # 1m crossover aligns with 4h downtrend -> short
                for pos in portfolio.positions:
                    if pos.side == "long":
                        signals.append(Signal.close(position_id=pos.id))
                signals.append(
                    Signal.open_short(
                        size_percent=self.risk_percent,
                        stop_loss=price_1m * (1 + self.sl_percent / 100),
                        take_profit=price_1m * (1 - self.tp_percent / 100),
                    )
                )

        self._prev_fast = fast_ma
        self._prev_slow = slow_ma
        return signals

    def get_state(self) -> dict[str, Any]:
        """Return serializable state for crash recovery."""
        return {
            "prev_fast": self._prev_fast,
            "prev_slow": self._prev_slow,
        }

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore state from a previously saved dict."""
        self._prev_fast = state.get("prev_fast")
        self._prev_slow = state.get("prev_slow")
