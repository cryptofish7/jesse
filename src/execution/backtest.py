"""Backtest executor — simulated trade execution at candle close prices."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from src.core.portfolio import Portfolio
from src.core.types import Position, Signal, Trade
from src.execution.executor import Executor

logger = logging.getLogger(__name__)

# Sentinel for unset current_time — uses min datetime with UTC to comply
# with project convention of timezone-aware datetimes.
_UNSET_TIME = datetime.min.replace(tzinfo=UTC)


class BacktestExecutor(Executor):
    """Fills trades at candle close price for backtesting.

    The executor returns Position/Trade objects but does NOT mutate the
    portfolio. The Engine is responsible for calling portfolio.open_position()
    and portfolio.close_position() after receiving non-None results. This
    separation allows the Engine to coordinate portfolio updates with
    persistence, alerts, and other side effects.

    The engine must set `current_time` before each execute/close cycle
    so that Position.entry_time and Trade.exit_time reflect the actual
    candle timestamp.
    """

    def __init__(self, initial_balance: float = 10_000.0) -> None:
        self.initial_balance = initial_balance
        self.current_time: datetime = _UNSET_TIME

    async def execute(
        self,
        signal: Signal,
        current_price: float,
        portfolio: Portfolio,
    ) -> Position | Trade | None:
        """Execute a signal at the current (candle close) price.

        Returns a Position for open signals, Trade for close signals,
        or None if rejected. The caller (Engine) must update the portfolio
        with the returned object.
        """
        if signal.direction in ("long", "short"):
            return self._open_position(signal, current_price, portfolio)
        elif signal.direction == "close":
            return self._close_by_signal(signal, current_price, portfolio)
        return None

    async def close_position(
        self,
        position: Position,
        price: float,
        reason: Literal["stop_loss", "take_profit", "signal"],
    ) -> Trade:
        """Close a position at the given price (SL/TP/signal)."""
        return _build_trade(position, price, self.current_time, reason)

    def _open_position(
        self,
        signal: Signal,
        price: float,
        portfolio: Portfolio,
    ) -> Position | None:
        """Create a new position from an open signal."""
        if signal.size_percent is None or signal.stop_loss is None or signal.take_profit is None:
            logger.warning("Rejecting open signal: missing size, SL, or TP")
            return None

        size_usd = portfolio.equity * signal.size_percent
        if size_usd <= 0:
            logger.warning("Rejecting open signal: zero or negative size")
            return None

        if size_usd > portfolio.balance:  # type: ignore[operator]
            logger.warning(
                "Rejecting open signal: insufficient balance (need %.2f, have %.2f)",
                size_usd,
                portfolio.balance,
            )
            return None

        if price <= 0:
            logger.warning("Rejecting open signal: invalid price %.6f", price)
            return None

        size = size_usd / price  # Base currency units (e.g., BTC)

        return Position(
            id=Position.generate_id(),
            side=signal.direction,  # type: ignore[arg-type]
            entry_price=price,
            entry_time=self.current_time,
            size=size,
            size_usd=size_usd,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )

    def _close_by_signal(
        self,
        signal: Signal,
        price: float,
        portfolio: Portfolio,
    ) -> Trade | None:
        """Close a position via a strategy close signal.

        If position_id is specified, closes that position.
        If position_id is None, closes the first open position.
        The engine is responsible for handling close-all by calling
        execute() repeatedly for each position.
        """
        if signal.position_id is not None:
            pos = portfolio.get_position(signal.position_id)
            if pos is None:
                logger.warning("Close signal for unknown position: %s", signal.position_id)
                return None
            return _build_trade(pos, price, self.current_time, "signal")

        if portfolio.positions:
            pos = portfolio.positions[0]
            return _build_trade(pos, price, self.current_time, "signal")

        return None


def _build_trade(
    position: Position,
    exit_price: float,
    exit_time: datetime,
    reason: Literal["stop_loss", "take_profit", "signal"],
) -> Trade:
    """Build a Trade from a position being closed."""
    if position.side == "long":
        pnl = (exit_price - position.entry_price) * position.size
    else:
        pnl = (position.entry_price - exit_price) * position.size

    pnl_percent = (pnl / position.size_usd) * 100 if position.size_usd > 0 else 0.0

    return Trade(
        id=position.id,
        side=position.side,
        entry_price=position.entry_price,
        exit_price=exit_price,
        entry_time=position.entry_time,
        exit_time=exit_time,
        size=position.size,
        size_usd=position.size_usd,
        pnl=pnl,
        pnl_percent=pnl_percent,
        exit_reason=reason,
    )
