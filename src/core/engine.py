"""Backtest engine — orchestrates data, strategy, execution, and portfolio."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.portfolio import Portfolio
from src.core.timeframe import TimeframeAggregator, get_timeframe_minutes
from src.core.types import Candle, Position, Signal, Trade
from src.data.provider import DataProvider
from src.execution.backtest import BacktestExecutor
from src.execution.executor import Executor
from src.execution.sl_tp import ExitReason, SLTPMonitor
from src.strategy.base import Strategy

if TYPE_CHECKING:
    from src.alerts.discord import DiscordAlerter
    from src.persistence.database import Database

logger = logging.getLogger(__name__)


# --- Result types ---


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """A single point on the equity curve."""

    timestamp: datetime
    equity: float


@dataclass
class BacktestResults:
    """Results from a completed backtest run."""

    trades: list[Trade]
    equity_curve: list[EquityPoint]
    start_time: datetime
    end_time: datetime
    initial_balance: float
    final_equity: float

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl > 0]

    @property
    def losing_trades(self) -> list[Trade]:
        return [t for t in self.trades if t.pnl < 0]

    @property
    def win_rate(self) -> float:
        """Fraction of winning trades (0.0 to 1.0). Returns 0.0 if no trades.

        Break-even trades (pnl == 0) count in the denominator but not
        as wins, so they dilute the win rate. This matches standard
        trading convention.
        """
        from src.analysis.metrics import calculate_win_rate

        return calculate_win_rate(self.trades)

    @property
    def profit_factor(self) -> float:
        """Gross profit / gross loss. Returns inf if no losses, 0.0 if no wins."""
        from src.analysis.metrics import calculate_profit_factor

        return calculate_profit_factor(self.trades)

    @property
    def total_return(self) -> float:
        """Total return as a decimal (e.g., 0.15 = 15%)."""
        from src.analysis.metrics import calculate_total_return

        return calculate_total_return(self.initial_balance, self.final_equity)

    @property
    def max_drawdown(self) -> float:
        """Maximum peak-to-trough drawdown as a decimal (e.g., 0.10 = 10%)."""
        from src.analysis.metrics import calculate_max_drawdown

        return calculate_max_drawdown(self.equity_curve)

    def summary(self) -> str:
        """Human-readable summary of backtest results."""
        pf_str = f"{self.profit_factor:.2f}" if self.profit_factor != float("inf") else "inf"
        lines = [
            "=" * 50,
            "BACKTEST RESULTS",
            "=" * 50,
            f"Period:          {self.start_time:%Y-%m-%d} to {self.end_time:%Y-%m-%d}",
            f"Initial Balance: ${self.initial_balance:,.2f}",
            f"Final Equity:    ${self.final_equity:,.2f}",
            f"Total Return:    {self.total_return:+.2%}",
            f"Total Trades:    {self.total_trades}",
            f"Win Rate:        {self.win_rate:.1%}",
            f"Profit Factor:   {pf_str}",
            f"Max Drawdown:    {self.max_drawdown:.2%}",
            "=" * 50,
        ]
        return "\n".join(lines)

    def plot_equity_curve(self, output_path: str | Path) -> None:
        """Save an interactive equity curve chart as HTML.

        Delegates to :func:`src.analysis.charts.plot_equity_curve`.
        """
        from src.analysis.charts import plot_equity_curve

        plot_equity_curve(self.equity_curve, output_path)

    def plot_trades(self, candles: list[Candle], output_path: str | Path) -> None:
        """Save an interactive candlestick + trade overlay chart as HTML.

        Delegates to :func:`src.analysis.charts.plot_trades`.
        """
        from src.analysis.charts import plot_trades

        plot_trades(candles, self.trades, output_path)

    def export_trades(self, output_path: str | Path) -> None:
        """Export trades to a CSV file.

        Columns: id, side, entry_price, exit_price, entry_time, exit_time,
        size, size_usd, pnl, pnl_percent, exit_reason.

        An empty trade list produces a CSV with headers only.
        """
        fieldnames = [
            "id",
            "side",
            "entry_price",
            "exit_price",
            "entry_time",
            "exit_time",
            "size",
            "size_usd",
            "pnl",
            "pnl_percent",
            "exit_reason",
        ]
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(str(output_path), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for trade in self.trades:
                writer.writerow(
                    {
                        "id": trade.id,
                        "side": trade.side,
                        "entry_price": trade.entry_price,
                        "exit_price": trade.exit_price,
                        "entry_time": trade.entry_time.isoformat(),
                        "exit_time": trade.exit_time.isoformat(),
                        "size": trade.size,
                        "size_usd": trade.size_usd,
                        "pnl": trade.pnl,
                        "pnl_percent": trade.pnl_percent,
                        "exit_reason": trade.exit_reason,
                    }
                )


# --- Engine ---


class Engine:
    """Orchestrates data flow between provider, strategy, executor, and portfolio.

    For backtesting:
        engine = Engine(strategy, data_provider, executor, start=..., end=...)
        results = await engine.run()

    The executor does NOT mutate the portfolio — the engine handles all
    portfolio bookkeeping (open_position, close_position) after receiving
    results from the executor.
    """

    def __init__(
        self,
        strategy: Strategy,
        data_provider: DataProvider,
        executor: Executor,
        alerter: DiscordAlerter | None = None,
        persist: bool = False,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> None:
        self.strategy = strategy
        self.data_provider = data_provider
        self.executor = executor
        self.alerter = alerter
        self.persist = persist
        self.start = start
        self.end = end

        initial_balance = (
            executor.initial_balance if isinstance(executor, BacktestExecutor) else 10_000.0
        )
        self.portfolio = Portfolio(initial_balance=initial_balance)
        self._sl_tp_monitor = SLTPMonitor()

        # Persistence — lazy runtime import to avoid circular imports
        self._db: Database | None = None
        if self.persist:
            from src.persistence.database import Database as _Database

            self._db = _Database()

    async def run(self) -> BacktestResults | None:
        """Main entry point. Returns BacktestResults for backtest, None for forward test."""
        try:
            if isinstance(self.executor, BacktestExecutor):
                return await self.run_backtest()
            raise NotImplementedError("Forward testing is not yet implemented")
        except Exception as exc:
            if self.alerter is not None:
                await self.alerter.on_error(f"{type(exc).__name__}: {exc}")
            raise

    async def run_backtest(self) -> BacktestResults:
        """Run a complete backtest over historical data.

        Steps:
        1. Fetch all 1m candles from the data provider.
        2. Split into warm-up and backtest periods.
        3. Warm up the aggregator and call strategy.on_init().
        4. Iterate candles: check SL/TP, call strategy, execute signals.
        5. Force-close remaining positions.
        6. Return results.
        """
        symbol = self._get_symbol()
        if self.start is None or self.end is None:
            raise ValueError("start and end must be set for backtest mode")

        logger.info("Starting backtest: %s from %s to %s", symbol, self.start, self.end)

        if self.alerter is not None:
            strategy_name = type(self.strategy).__name__
            await self.alerter.on_strategy_start(strategy_name)

        if self._db is not None:
            await self._db.initialize()

        try:
            if self._db is not None:
                await self._restore_state()
            candles_1m = await self.data_provider.get_historical_candles(
                symbol=symbol, timeframe="1m", start=self.start, end=self.end
            )

            if not candles_1m:
                logger.warning("No candle data returned for the requested range")
                return BacktestResults(
                    trades=[],
                    equity_curve=[],
                    start_time=self.start,
                    end_time=self.end,
                    initial_balance=self.portfolio.initial_balance,
                    final_equity=self.portfolio.initial_balance,
                )

            aggregator = TimeframeAggregator(timeframes=self.strategy.timeframes)

            warm_up_bars = self._calculate_warm_up_bars()
            warm_up_candles = candles_1m[:warm_up_bars]
            backtest_candles = candles_1m[warm_up_bars:]

            if not backtest_candles:
                logger.warning("All data consumed by warm-up, no candles for backtesting")
                return BacktestResults(
                    trades=[],
                    equity_curve=[],
                    start_time=candles_1m[0].timestamp,
                    end_time=candles_1m[-1].timestamp,
                    initial_balance=self.portfolio.initial_balance,
                    final_equity=self.portfolio.initial_balance,
                )

            # Warm up: feed all but last through warm_up, last through update for on_init
            if warm_up_candles:
                if len(warm_up_candles) > 1:
                    aggregator.warm_up(warm_up_candles[:-1])
                init_data = aggregator.update(warm_up_candles[-1])
                self.strategy.on_init(init_data)

            # Main backtest loop
            equity_curve: list[EquityPoint] = []

            for candle in backtest_candles:
                mtf_data = aggregator.update(candle)

                if isinstance(self.executor, BacktestExecutor):
                    self.executor.current_time = candle.timestamp

                self.portfolio.update_price(candle.close)

                # SL/TP check BEFORE strategy (stops execute before strategy reacts)
                await self._check_sl_tp(candle)

                signals = self.strategy.on_candle(mtf_data, self.portfolio) or []

                for signal in signals:
                    await self._execute_signal(signal, candle.close)

                equity_curve.append(
                    EquityPoint(
                        timestamp=candle.timestamp,
                        equity=self.portfolio.equity,
                    )
                )

            # Force-close remaining positions
            last_candle = backtest_candles[-1]
            await self._close_all_positions(last_candle.close, last_candle.timestamp)

            await self._save_state()

            results = BacktestResults(
                trades=list(self.portfolio.trades),
                equity_curve=equity_curve,
                start_time=backtest_candles[0].timestamp,
                end_time=last_candle.timestamp,
                initial_balance=self.portfolio.initial_balance,
                final_equity=self.portfolio.equity,
            )

            logger.info("Backtest complete.\n%s", results.summary())
            return results
        finally:
            if self._db is not None:
                await self._db.close()

    async def _restore_state(self) -> None:
        """Restore portfolio and strategy state from the database.

        Called at the start of a backtest/forward-test when persist=True.
        Clears any existing portfolio positions before restoring from DB
        to prevent duplicates.
        """
        if self._db is None:
            return

        saved_portfolio = await self._db.get_portfolio()
        if saved_portfolio is not None:
            self.portfolio.balance = saved_portfolio.balance
            logger.info("Restored portfolio balance: %.2f", saved_portfolio.balance)

        self.portfolio.positions.clear()
        positions = await self._db.get_open_positions()
        for pos in positions:
            self.portfolio.positions.append(pos)
        if positions:
            logger.info("Restored %d open positions", len(positions))

        strategy_name = type(self.strategy).__name__
        state = await self._db.get_strategy_state(strategy_name)
        if state is not None:
            self.strategy.set_state(state)
            logger.info("Restored strategy state for %s", strategy_name)

    async def _save_state(self) -> None:
        """Persist portfolio and strategy state to the database.

        Called at the end of the backtest loop when persist=True.
        """
        if self._db is None:
            return

        await self._db.save_portfolio(self.portfolio)
        strategy_name = type(self.strategy).__name__
        await self._db.save_strategy_state(strategy_name, self.strategy.get_state())
        logger.info("Saved portfolio and strategy state")

    async def _check_sl_tp(self, candle: Candle) -> None:
        """Check all open positions for SL/TP hits and close if triggered."""
        for position in list(self.portfolio.positions):
            result = self._sl_tp_monitor.check(position, candle)
            if result is not None:
                exit_price = self._get_exit_price(position, result)
                trade = await self.executor.close_position(position, exit_price, result)
                self.portfolio.close_position(position.id, trade)
                if self._db is not None:
                    await self._db.delete_position(position.id)
                    await self._db.save_trade(trade)
                if self.alerter is not None:
                    await self.alerter.on_trade_close(trade)
                logger.debug(
                    "Position %s closed by %s at %.2f (PnL: %.2f)",
                    position.id,
                    result,
                    exit_price,
                    trade.pnl,
                )

    def _get_exit_price(self, position: Position, reason: ExitReason) -> float:
        """Get the exact SL or TP price for the exit."""
        if reason == "stop_loss":
            return position.stop_loss
        return position.take_profit

    async def _execute_signal(self, signal: Signal, current_price: float) -> None:
        """Execute a single signal and update the portfolio."""
        result = await self.executor.execute(signal, current_price, self.portfolio)
        if result is None:
            return

        if isinstance(result, Position):
            self.portfolio.open_position(result)
            if self._db is not None:
                await self._db.save_position(result)
            if self.alerter is not None:
                await self.alerter.on_trade_open(result)
            logger.debug(
                "Opened %s position %s at %.2f (size: $%.2f)",
                result.side,
                result.id,
                result.entry_price,
                result.size_usd,
            )
        elif isinstance(result, Trade):
            self.portfolio.close_position(result.id, result)
            if self._db is not None:
                await self._db.delete_position(result.id)
                await self._db.save_trade(result)
            if self.alerter is not None:
                await self.alerter.on_trade_close(result)
            logger.debug(
                "Closed position %s by signal at %.2f (PnL: %.2f)",
                result.id,
                result.exit_price,
                result.pnl,
            )

    async def _close_all_positions(self, price: float, timestamp: datetime) -> None:
        """Force-close all remaining open positions at end of backtest.

        Uses exit_reason="signal" since the existing type system only supports
        "stop_loss", "take_profit", and "signal". These force-closes are
        identifiable in logs via the "End-of-backtest" prefix.

        Persists each closed trade and removes the position from the DB
        so that crash-recovery does not re-open already-closed positions.
        """
        if isinstance(self.executor, BacktestExecutor):
            self.executor.current_time = timestamp

        for position in list(self.portfolio.positions):
            trade = await self.executor.close_position(position, price, "signal")
            self.portfolio.close_position(position.id, trade)
            if self._db is not None:
                await self._db.delete_position(position.id)
                await self._db.save_trade(trade)
            logger.debug(
                "End-of-backtest: force-closed position %s at %.2f (PnL: %.2f)",
                position.id,
                price,
                trade.pnl,
            )

    def _get_symbol(self) -> str:
        """Get symbol from the data provider or config."""
        if hasattr(self.data_provider, "symbol"):
            return str(self.data_provider.symbol)  # type: ignore[attr-defined]
        from src.config import settings

        return settings.symbol

    def _calculate_warm_up_bars(self) -> int:
        """Calculate warm-up period: enough for 1 candle of the highest declared TF."""
        max_minutes = max(get_timeframe_minutes(tf) for tf in self.strategy.timeframes)
        return max(max_minutes, 100)
