"""SL/TP monitoring and drill-down resolution."""

from __future__ import annotations

import logging
from typing import Literal

from src.core.timeframe import get_lower_timeframe
from src.core.types import Candle, Position

logger = logging.getLogger(__name__)

ExitReason = Literal["stop_loss", "take_profit"]


class SLTPMonitor:
    """Monitors positions for stop-loss and take-profit hits.

    Usage (single-call API):
        result = monitor.check(position, candle, available_candles, "1m")
        # Returns "stop_loss", "take_profit", or None

    When both SL and TP are hit on the same candle:
    - If available_candles is provided, drills down to lower timeframes.
    - If no drill-down data is available, falls back to "stop_loss" (conservative).
    """

    def check(
        self,
        position: Position,
        candle: Candle,
        available_candles: dict[str, list[Candle]] | None = None,
        current_timeframe: str = "1m",
    ) -> ExitReason | None:
        """Check if a position's SL or TP is hit by a candle.

        Returns 'stop_loss', 'take_profit', or None (neither hit).
        When both are hit, resolves via drill-down if available_candles
        is provided, otherwise falls back to 'stop_loss' (conservative).
        """
        sl_hit = self._sl_hit(position, candle)
        tp_hit = self._tp_hit(position, candle)

        if sl_hit and tp_hit:
            if available_candles is not None:
                return self.resolve(position, candle, available_candles, current_timeframe)
            # No drill-down data — conservative fallback
            return "stop_loss"
        if sl_hit:
            return "stop_loss"
        if tp_hit:
            return "take_profit"
        return None

    def resolve(
        self,
        position: Position,
        candle: Candle,
        available_candles: dict[str, list[Candle]],
        current_timeframe: str,
    ) -> ExitReason:
        """Resolve which exit hit first when both SL and TP are hit on one candle.

        Drills down through lower timeframes to find which was hit first.
        Falls back to 'stop_loss' (conservative) at 1m if still ambiguous.

        Args:
            position: The position to check.
            candle: The candle where both SL and TP were hit.
            available_candles: Dict mapping timeframe -> list of sub-candles.
                Each timeframe's candles must be pre-filtered to the parent
                candle's time window by the caller (Engine). The monitor does
                not filter by timestamp — it trusts the provided data.
            current_timeframe: The timeframe of the current candle (required).
        """
        result = self._resolve_recursive(position, candle, available_candles, current_timeframe)
        # _resolve_recursive returns None only for sub-candles where neither is hit,
        # but resolve() is only called when both are hit on the parent candle,
        # so the fallback guarantees a non-None result.
        return result if result is not None else "stop_loss"

    def _resolve_recursive(
        self,
        position: Position,
        candle: Candle,
        available_candles: dict[str, list[Candle]],
        current_timeframe: str,
    ) -> ExitReason | None:
        """Recursively drill down to resolve SL/TP ambiguity."""
        sl_hit = self._sl_hit(position, candle)
        tp_hit = self._tp_hit(position, candle)

        if sl_hit and tp_hit:
            next_tf = get_lower_timeframe(current_timeframe)

            if next_tf is None:
                # At 1m, cannot drill further — conservative fallback
                logger.debug(
                    "SL/TP both hit at 1m for position %s, assuming SL (conservative)",
                    position.id,
                )
                return "stop_loss"

            sub_candles = available_candles.get(next_tf, [])
            if not sub_candles:
                # No lower-timeframe data available — conservative fallback
                logger.debug(
                    "No %s candles available for drill-down, assuming SL for position %s",
                    next_tf,
                    position.id,
                )
                return "stop_loss"

            for sub_candle in sub_candles:
                result = self._resolve_recursive(position, sub_candle, available_candles, next_tf)
                if result is not None:
                    return result

            # All sub-candles had neither hit — conservative fallback
            return "stop_loss"

        elif sl_hit:
            return "stop_loss"
        elif tp_hit:
            return "take_profit"

        # Neither hit on this sub-candle — signal to continue iteration
        return None

    def _sl_hit(self, position: Position, candle: Candle) -> bool:
        """Check if stop-loss is hit."""
        if position.side == "long":
            return candle.low <= position.stop_loss
        else:
            return candle.high >= position.stop_loss

    def _tp_hit(self, position: Position, candle: Candle) -> bool:
        """Check if take-profit is hit."""
        if position.side == "long":
            return candle.high >= position.take_profit
        else:
            return candle.low <= position.take_profit
