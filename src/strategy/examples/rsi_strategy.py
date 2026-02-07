"""RSI overbought/oversold strategy — example implementation.

Opens a long when RSI drops below an oversold threshold, and opens a short
when RSI rises above an overbought threshold. Closes positions on the
opposite signal.

RSI is calculated using the classic Wilder smoothing method over a
configurable lookback period.
"""

from __future__ import annotations

from typing import Any

from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Signal
from src.strategy.base import Strategy


def _rsi(candles: list[Candle], period: int) -> float | None:
    """Calculate the Relative Strength Index using Wilder smoothing.

    Returns a value between 0 and 100, or None if there are not
    enough candles (need at least ``period + 1`` to compute deltas).
    """
    if len(candles) < period + 1:
        return None

    # Calculate price changes (close-to-close)
    deltas = [candles[i].close - candles[i - 1].close for i in range(1, len(candles))]

    # Seed the averages with a simple mean of the first `period` deltas
    gains = [max(d, 0.0) for d in deltas[:period]]
    losses = [max(-d, 0.0) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # Wilder smoothing for the remaining deltas
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period

    if avg_loss == 0.0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


class RSIStrategy(Strategy):
    """RSI overbought/oversold mean-reversion strategy.

    Opens a long when RSI drops below ``oversold`` (default 30) and opens
    a short when RSI rises above ``overbought`` (default 70). Each new
    signal closes any existing position on the opposite side first.

    Parameters:
        period: RSI lookback period (default: 14).
        overbought: RSI threshold for short entry (default: 70).
        oversold: RSI threshold for long entry (default: 30).
        risk_percent: Position size as fraction of equity (default: 1.0 = 100%).
        sl_percent: Stop loss distance as % of entry price (default: 2.0).
        tp_percent: Take profit distance as % of entry price (default: 4.0).
    """

    timeframes = ["1m"]

    def __init__(
        self,
        period: int = 14,
        overbought: float = 70.0,
        oversold: float = 30.0,
        risk_percent: float = 1.0,
        sl_percent: float = 2.0,
        tp_percent: float = 4.0,
    ) -> None:
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.risk_percent = risk_percent
        self.sl_percent = sl_percent
        self.tp_percent = tp_percent
        self._prev_rsi: float | None = None

    def on_candle(
        self,
        data: MultiTimeframeData,
        portfolio: Portfolio,
    ) -> list[Signal]:
        candles = data["1m"].history
        price = data["1m"].latest.close

        current_rsi = _rsi(candles, self.period)
        if current_rsi is None:
            return []

        signals: list[Signal] = []

        # Need previous RSI to detect threshold crossings
        if self._prev_rsi is not None:
            crossed_below_oversold = self._prev_rsi >= self.oversold and current_rsi < self.oversold
            crossed_above_overbought = (
                self._prev_rsi <= self.overbought and current_rsi > self.overbought
            )

            if crossed_below_oversold:
                # RSI dropped into oversold territory -> long entry
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

            elif crossed_above_overbought:
                # RSI rose into overbought territory -> short entry
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

        self._prev_rsi = current_rsi
        return signals

    def get_state(self) -> dict[str, Any]:
        """Return serializable state for crash recovery."""
        return {"prev_rsi": self._prev_rsi}

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore state from a previously saved dict."""
        self._prev_rsi = state.get("prev_rsi")
