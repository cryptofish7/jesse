"""Paper executor — simulated order execution for forward testing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from src.core.portfolio import Portfolio
from src.core.types import Position, Signal, Trade
from src.execution.executor import Executor

logger = logging.getLogger(__name__)

# Type alias for the position-change callback.
# Called with (event, position_or_trade) where event is one of:
#   "opened", "closed_sl", "closed_tp", "closed_signal"
PositionChangeCallback = Callable[[str, Position | Trade], None]


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


class PaperExecutor(Executor):
    """Simulates order execution for forward (paper) testing.

    Key differences from BacktestExecutor:
    - Fills at the current market price (passed as ``current_price``).
    - Uses real wall-clock time (``datetime.now(UTC)``) for timestamps.
    - Provides :meth:`check_price_update` for tick-level SL/TP monitoring
      (not limited to candle close like the backtest engine).
    - Supports an optional callback for position-change alerts.

    Like BacktestExecutor, PaperExecutor does NOT mutate the portfolio.
    The caller (Engine) is responsible for calling ``portfolio.open_position()``
    and ``portfolio.close_position()`` after receiving non-None results.

    The exception is :meth:`check_price_update`, which both detects SL/TP
    triggers AND closes positions on the portfolio, returning the list of
    resulting trades. This is a convenience for the forward-testing loop
    where tick-level monitoring must be tightly coupled with portfolio updates
    to avoid double-fills.
    """

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        on_position_change: PositionChangeCallback | None = None,
    ) -> None:
        self.initial_balance = initial_balance
        self.on_position_change = on_position_change

    async def execute(
        self,
        signal: Signal,
        current_price: float,
        portfolio: Portfolio,
    ) -> Position | Trade | None:
        """Execute a signal at the current market price.

        Returns a Position for open signals, Trade for close signals,
        or None if rejected. The caller (Engine) must update the portfolio
        with the returned object.
        """
        if signal.direction in ("long", "short"):
            position = self._open_position(signal, current_price, portfolio)
            if position is not None and self.on_position_change is not None:
                self.on_position_change("opened", position)
            return position
        elif signal.direction == "close":
            trade = self._close_by_signal(signal, current_price, portfolio)
            if trade is not None and self.on_position_change is not None:
                self.on_position_change("closed_signal", trade)
            return trade
        return None

    async def close_position(
        self,
        position: Position,
        price: float,
        reason: Literal["stop_loss", "take_profit", "signal"],
    ) -> Trade:
        """Close a position at the given price (SL/TP/signal)."""
        now = datetime.now(UTC)
        trade = _build_trade(position, price, now, reason)
        if self.on_position_change is not None:
            event = f"closed_{reason}"
            self.on_position_change(event, trade)
        return trade

    def check_price_update(
        self,
        price: float,
        portfolio: Portfolio,
    ) -> list[Trade]:
        """Check all positions for SL/TP hits at the current tick price.

        This is the tick-level monitoring method that should be called on
        every price update during forward testing. It:

        1. Updates the portfolio's last known price (for equity calculation).
        2. Checks each open position's SL and TP against the raw price.
        3. Closes any triggered positions on the portfolio.
        4. Fires the position-change callback for each triggered trade.

        Returns a list of Trades for positions that were closed. An empty
        list means no SL/TP was hit.

        Note: Unlike the SLTPMonitor used in backtesting (which operates on
        candle high/low), this checks the exact tick price. In forward
        testing the price stream provides individual price points, so
        candle-based drill-down is unnecessary.
        """
        portfolio.update_price(price)

        triggered_trades: list[Trade] = []
        now = datetime.now(UTC)

        for position in list(portfolio.positions):
            reason = self._check_sl_tp(position, price)
            if reason is None:
                continue

            exit_price = position.stop_loss if reason == "stop_loss" else position.take_profit
            trade = _build_trade(position, exit_price, now, reason)
            portfolio.close_position(position.id, trade)
            triggered_trades.append(trade)

            if self.on_position_change is not None:
                event = f"closed_{reason}"
                self.on_position_change(event, trade)

            logger.info(
                "Paper position %s closed by %s at %.2f (PnL: %.2f)",
                position.id,
                reason,
                exit_price,
                trade.pnl,
            )

        return triggered_trades

    # --- Private helpers ---

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
        now = datetime.now(UTC)

        return Position(
            id=Position.generate_id(),
            side=signal.direction,  # type: ignore[arg-type]
            entry_price=price,
            entry_time=now,
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
        """
        now = datetime.now(UTC)

        if signal.position_id is not None:
            pos = portfolio.get_position(signal.position_id)
            if pos is None:
                logger.warning("Close signal for unknown position: %s", signal.position_id)
                return None
            return _build_trade(pos, price, now, "signal")

        if portfolio.positions:
            pos = portfolio.positions[0]
            return _build_trade(pos, price, now, "signal")

        return None

    @staticmethod
    def _check_sl_tp(
        position: Position,
        price: float,
    ) -> Literal["stop_loss", "take_profit"] | None:
        """Check if a position's SL or TP is hit by the current tick price.

        For tick-level checking, the price is a single value (not a candle
        with high/low), so at most one of SL/TP can be hit at a time.
        If, due to a gap, both would be triggered, we conservatively
        return stop_loss first.
        """
        sl_hit = False
        tp_hit = False

        if position.side == "long":
            sl_hit = price <= position.stop_loss
            tp_hit = price >= position.take_profit
        else:  # short
            sl_hit = price >= position.stop_loss
            tp_hit = price <= position.take_profit

        # Conservative: SL takes priority if both somehow triggered
        if sl_hit:
            return "stop_loss"
        if tp_hit:
            return "take_profit"
        return None
