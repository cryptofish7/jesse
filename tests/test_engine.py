"""Tests for the backtest engine and BacktestResults."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.engine import BacktestResults, Engine, EquityPoint
from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Signal, Trade
from src.data.provider import DataProvider
from src.execution.backtest import BacktestExecutor
from src.strategy.base import Strategy

# --- Test helpers ---


class FakeDataProvider(DataProvider):
    """Returns pre-loaded candles for testing."""

    def __init__(self, candles: list[Candle], symbol: str = "BTC/USDT:USDT") -> None:
        self.candles = candles
        self.symbol = symbol

    async def get_historical_candles(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Candle]:
        return self.candles

    async def subscribe(self, symbol, timeframes, callback) -> None:  # type: ignore[override]
        raise NotImplementedError

    async def unsubscribe(self) -> None:
        pass


class NeverTradeStrategy(Strategy):
    """Strategy that never emits signals."""

    timeframes = ["1m"]

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        return []


class OpenOnceStrategy(Strategy):
    """Opens a long on the first candle, never closes."""

    timeframes = ["1m"]

    def __init__(self, sl_pct: float = 0.05, tp_pct: float = 0.10) -> None:
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self._opened = False

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        if not self._opened and not portfolio.has_position:
            self._opened = True
            price = data["1m"].latest.close
            return [
                Signal.open_long(
                    size_percent=0.5,
                    stop_loss=price * (1 - self.sl_pct),
                    take_profit=price * (1 + self.tp_pct),
                )
            ]
        return []


class OpenShortOnceStrategy(Strategy):
    """Opens a short on the first candle."""

    timeframes = ["1m"]

    def __init__(self, sl_pct: float = 0.05, tp_pct: float = 0.10) -> None:
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self._opened = False

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        if not self._opened and not portfolio.has_position:
            self._opened = True
            price = data["1m"].latest.close
            return [
                Signal.open_short(
                    size_percent=0.5,
                    stop_loss=price * (1 + self.sl_pct),
                    take_profit=price * (1 - self.tp_pct),
                )
            ]
        return []


class MultiPositionStrategy(Strategy):
    """Opens a new long position every N candles."""

    timeframes = ["1m"]

    def __init__(self, interval: int = 5) -> None:
        self.interval = interval
        self._count = 0

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        self._count += 1
        if self._count % self.interval == 1:
            price = data["1m"].latest.close
            return [
                Signal.open_long(
                    size_percent=0.1,
                    stop_loss=price * 0.90,
                    take_profit=price * 1.20,
                )
            ]
        return []


class MultiTFStrategy(Strategy):
    """Strategy that uses multiple timeframes."""

    timeframes = ["1m", "5m"]

    def __init__(self) -> None:
        self.saw_5m = False

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        if "5m" in data and len(data["5m"].history) > 0:
            self.saw_5m = True
        return []


def _make_candles(
    n: int,
    start_price: float = 100.0,
    trend: float = 0.0,
    base_time: datetime | None = None,
) -> list[Candle]:
    """Generate n 1m candles with optional linear trend."""
    if base_time is None:
        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    candles = []
    for i in range(n):
        price = start_price + (trend * i)
        candles.append(
            Candle(
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=100.0,
            )
        )
    return candles


def _make_candles_with_dip(
    n: int,
    start_price: float = 100.0,
    dip_at: int = 50,
    dip_amount: float = 20.0,
    base_time: datetime | None = None,
) -> list[Candle]:
    """Generate candles with a dip at a specific index (low goes to start_price - dip_amount)."""
    if base_time is None:
        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    candles = []
    for i in range(n):
        price = start_price
        low = price - 1.0
        high = price + 1.0
        if i == dip_at:
            low = price - dip_amount
        candles.append(
            Candle(
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=high,
                low=low,
                close=price + 0.5,
                volume=100.0,
            )
        )
    return candles


def _make_candles_with_spike(
    n: int,
    start_price: float = 100.0,
    spike_at: int = 50,
    spike_amount: float = 20.0,
    base_time: datetime | None = None,
) -> list[Candle]:
    """Generate candles with a spike at a specific index (high goes up)."""
    if base_time is None:
        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    candles = []
    for i in range(n):
        price = start_price
        low = price - 1.0
        high = price + 1.0
        if i == spike_at:
            high = price + spike_amount
        candles.append(
            Candle(
                timestamp=base_time + timedelta(minutes=i),
                open=price,
                high=high,
                low=low,
                close=price + 0.5,
                volume=100.0,
            )
        )
    return candles


# --- BacktestResults unit tests ---


class TestBacktestResults:
    _T1 = datetime(2024, 1, 1, tzinfo=UTC)
    _T2 = datetime(2024, 1, 2, tzinfo=UTC)

    def _make_trade(self, pnl: float) -> Trade:
        return Trade(
            id="t1",
            side="long",
            entry_price=100.0,
            exit_price=100.0 + pnl,
            entry_time=self._T1,
            exit_time=self._T2,
            size=1.0,
            size_usd=100.0,
            pnl=pnl,
            pnl_percent=(pnl / 100.0) * 100,
            exit_reason="signal",
        )

    def _results(
        self,
        trades: list[Trade] | None = None,
        equity_curve: list[EquityPoint] | None = None,
        initial_balance: float = 10_000.0,
        final_equity: float = 10_000.0,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> BacktestResults:
        return BacktestResults(
            trades=trades or [],
            equity_curve=equity_curve or [],
            start_time=start_time or self._T1,
            end_time=end_time or self._T2,
            initial_balance=initial_balance,
            final_equity=final_equity,
        )

    def test_win_rate_all_winners(self) -> None:
        trades = [self._make_trade(10), self._make_trade(5), self._make_trade(3)]
        r = self._results(trades=trades, final_equity=10018)
        assert r.win_rate == pytest.approx(1.0)

    def test_win_rate_all_losers(self) -> None:
        trades = [self._make_trade(-10), self._make_trade(-5), self._make_trade(-3)]
        r = self._results(trades=trades, final_equity=9982)
        assert r.win_rate == pytest.approx(0.0)

    def test_win_rate_mixed(self) -> None:
        trades = [self._make_trade(10), self._make_trade(5), self._make_trade(-3)]
        r = self._results(trades=trades, final_equity=10012)
        assert r.win_rate == pytest.approx(2 / 3)

    def test_win_rate_no_trades(self) -> None:
        assert self._results().win_rate == 0.0

    def test_profit_factor_normal(self) -> None:
        trades = [self._make_trade(30), self._make_trade(-10)]
        r = self._results(trades=trades, final_equity=10020)
        assert r.profit_factor == pytest.approx(3.0)

    def test_profit_factor_no_losses(self) -> None:
        trades = [self._make_trade(10), self._make_trade(5)]
        r = self._results(trades=trades, final_equity=10015)
        assert r.profit_factor == float("inf")

    def test_profit_factor_no_wins(self) -> None:
        trades = [self._make_trade(-10)]
        r = self._results(trades=trades, final_equity=9990)
        assert r.profit_factor == 0.0

    def test_profit_factor_no_trades(self) -> None:
        assert self._results().profit_factor == 0.0

    def test_total_return_positive(self) -> None:
        assert self._results(final_equity=11500).total_return == pytest.approx(0.15)

    def test_total_return_negative(self) -> None:
        assert self._results(final_equity=8000).total_return == pytest.approx(-0.20)

    def test_total_return_flat(self) -> None:
        assert self._results().total_return == pytest.approx(0.0)

    def test_max_drawdown_basic(self) -> None:
        curve = [
            EquityPoint(datetime(2024, 1, 1, 0, i, tzinfo=UTC), eq)
            for i, eq in enumerate([100, 110, 90, 120])
        ]
        r = self._results(
            equity_curve=curve,
            initial_balance=100,
            final_equity=120,
            start_time=curve[0].timestamp,
            end_time=curve[-1].timestamp,
        )
        # Peak = 110, trough = 90, dd = 20/110
        assert r.max_drawdown == pytest.approx(20.0 / 110.0)

    def test_max_drawdown_no_decline(self) -> None:
        curve = [
            EquityPoint(datetime(2024, 1, 1, 0, i, tzinfo=UTC), eq)
            for i, eq in enumerate([100, 105, 110])
        ]
        r = self._results(
            equity_curve=curve,
            initial_balance=100,
            final_equity=110,
            start_time=curve[0].timestamp,
            end_time=curve[-1].timestamp,
        )
        assert r.max_drawdown == pytest.approx(0.0)

    def test_max_drawdown_empty_curve(self) -> None:
        assert self._results().max_drawdown == 0.0

    def test_summary_contains_key_fields(self) -> None:
        r = self._results(
            final_equity=11000,
            end_time=datetime(2024, 6, 1, tzinfo=UTC),
        )
        s = r.summary()
        assert "BACKTEST RESULTS" in s
        assert "10,000.00" in s
        assert "11,000.00" in s
        assert "Win Rate" in s


# --- Engine init tests ---


class TestEngineInit:
    def test_portfolio_uses_executor_balance(self) -> None:
        executor = BacktestExecutor(initial_balance=5_000.0)
        engine = Engine(
            strategy=NeverTradeStrategy(),
            data_provider=FakeDataProvider([]),
            executor=executor,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        assert engine.portfolio.initial_balance == 5_000.0

    @pytest.mark.asyncio
    async def test_backtest_requires_start_end(self) -> None:
        engine = Engine(
            strategy=NeverTradeStrategy(),
            data_provider=FakeDataProvider([]),
            executor=BacktestExecutor(),
        )
        with pytest.raises(ValueError, match="start and end must be set"):
            await engine.run()


# --- Engine backtest integration tests ---


class TestEngineBacktest:
    @pytest.mark.asyncio
    async def test_empty_data_returns_empty_results(self) -> None:
        engine = Engine(
            strategy=NeverTradeStrategy(),
            data_provider=FakeDataProvider([]),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        assert results.total_trades == 0
        assert results.equity_curve == []
        assert results.final_equity == 10_000.0

    @pytest.mark.asyncio
    async def test_no_signals_flat_equity(self) -> None:
        candles = _make_candles(200, start_price=100.0)
        engine = Engine(
            strategy=NeverTradeStrategy(),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        assert results.total_trades == 0
        # Equity should be flat (all warm-up=100, 100 backtest candles)
        assert results.final_equity == pytest.approx(10_000.0)

    @pytest.mark.asyncio
    async def test_single_long_trade_tp(self) -> None:
        """Open long, price spikes to hit TP."""
        # 200 candles: first 100 warm-up, then on candle 101 strategy opens long
        # at ~100.5 close. TP = 100.5 * 1.10 = 110.55. Spike at candle 150 (idx 150).
        candles = _make_candles_with_spike(200, start_price=100.0, spike_at=150, spike_amount=15.0)
        engine = Engine(
            strategy=OpenOnceStrategy(sl_pct=0.05, tp_pct=0.10),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        assert results.total_trades == 1
        assert results.trades[0].exit_reason == "take_profit"
        assert results.trades[0].pnl > 0

    @pytest.mark.asyncio
    async def test_single_short_trade_sl(self) -> None:
        """Open short, price spikes to hit SL."""
        # Short at ~100.5, SL = 100.5 * 1.05 = 105.525. Spike high at candle 150.
        candles = _make_candles_with_spike(200, start_price=100.0, spike_at=150, spike_amount=10.0)
        engine = Engine(
            strategy=OpenShortOnceStrategy(sl_pct=0.05, tp_pct=0.10),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        assert results.total_trades == 1
        assert results.trades[0].exit_reason == "stop_loss"
        assert results.trades[0].pnl < 0

    @pytest.mark.asyncio
    async def test_sl_tp_uses_exact_price(self) -> None:
        """Exit price should be the exact SL/TP level, not candle close."""
        candles = _make_candles_with_spike(200, start_price=100.0, spike_at=150, spike_amount=15.0)
        engine = Engine(
            strategy=OpenOnceStrategy(sl_pct=0.05, tp_pct=0.10),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        trade = results.trades[0]
        # TP should be entry_price * 1.10 (exact TP level)
        expected_tp = trade.entry_price * 1.10
        assert trade.exit_price == pytest.approx(expected_tp)

    @pytest.mark.asyncio
    async def test_multiple_positions(self) -> None:
        """Multiple positions opened and force-closed at end."""
        candles = _make_candles(200, start_price=100.0)
        engine = Engine(
            strategy=MultiPositionStrategy(interval=20),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        # Multiple trades should be recorded (force-closed at end)
        assert results.total_trades >= 2

    @pytest.mark.asyncio
    async def test_force_close_at_end(self) -> None:
        """Positions still open at end are force-closed."""
        candles = _make_candles(200, start_price=100.0)
        engine = Engine(
            strategy=OpenOnceStrategy(sl_pct=0.50, tp_pct=0.50),  # Wide SL/TP, won't hit
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        # Position should be force-closed
        assert results.total_trades == 1
        assert results.trades[0].exit_reason == "signal"  # Force-close uses "signal"

    @pytest.mark.asyncio
    async def test_equity_curve_length(self) -> None:
        """Equity curve should have one point per backtest candle."""
        candles = _make_candles(200, start_price=100.0)
        engine = Engine(
            strategy=NeverTradeStrategy(),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        warm_up = max(1, 100)  # 1m strategy, warm_up = max(1, 100) = 100
        expected_len = 200 - warm_up
        assert len(results.equity_curve) == expected_len

    @pytest.mark.asyncio
    async def test_equity_tracks_profitable_trade(self) -> None:
        """After a profitable trade, final equity is higher than initial."""
        candles = _make_candles_with_spike(200, start_price=100.0, spike_at=150, spike_amount=15.0)
        engine = Engine(
            strategy=OpenOnceStrategy(sl_pct=0.05, tp_pct=0.10),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        assert results.final_equity > results.initial_balance

    @pytest.mark.asyncio
    async def test_warm_up_calls_on_init(self) -> None:
        """Verify on_init is called during warm-up."""

        class InitTracker(Strategy):
            timeframes = ["1m"]
            init_called = False

            def on_init(self, data: MultiTimeframeData) -> None:
                InitTracker.init_called = True

            def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
                return []

        candles = _make_candles(200)
        engine = Engine(
            strategy=InitTracker(),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        await engine.run()
        assert InitTracker.init_called

    @pytest.mark.asyncio
    async def test_multi_timeframe_strategy(self) -> None:
        """Strategy with ['1m', '5m'] receives 5m data."""
        # Need at least 100 warm-up + some backtest candles
        candles = _make_candles(200)
        strategy = MultiTFStrategy()
        engine = Engine(
            strategy=strategy,
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        await engine.run()
        assert strategy.saw_5m

    @pytest.mark.asyncio
    async def test_position_closed_before_strategy(self) -> None:
        """SL triggers before strategy sees the candle — strategy close is a no-op.

        Strategy opens on candle 100 (first backtest candle), dip at candle 101
        triggers SL. Strategy also tries to close on candle 101 but SL already
        fired (SL check runs before on_candle), so close signal finds no position.
        """

        class CloseAfterOpen(Strategy):
            timeframes = ["1m"]

            def __init__(self) -> None:
                self._opened = False

            def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
                if not self._opened:
                    self._opened = True
                    price = data["1m"].latest.close
                    return [
                        Signal.open_long(
                            size_percent=0.5,
                            stop_loss=price * 0.95,
                            take_profit=price * 1.50,
                        )
                    ]
                # Always try to close — but SL should have already closed it
                if portfolio.has_position:
                    return [Signal.close()]
                return []

        # Dip at candle 101 (second backtest candle) triggers SL immediately
        candles = _make_candles_with_dip(200, start_price=100.0, dip_at=101, dip_amount=10.0)
        engine = Engine(
            strategy=CloseAfterOpen(),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        # Should have exactly 1 trade closed by SL
        assert results.total_trades == 1
        assert results.trades[0].exit_reason == "stop_loss"


# --- End-to-end with MACrossover ---


class TestEngineMACrossover:
    @pytest.mark.asyncio
    async def test_ma_crossover_regime_change(self) -> None:
        """Run MACrossover on data with a regime change — should generate trades."""
        from src.strategy.examples.ma_crossover import MACrossover

        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        # Build data with a regime change: decline then rally to force a crossover.
        # 200 candles declining (fast MA < slow MA), then 200 candles rallying
        # (fast MA crosses above slow MA). Total 400 candles.
        candles: list[Candle] = []
        for i in range(200):
            price = 100.0 - (i * 0.05)  # Slow decline
            candles.append(
                Candle(
                    timestamp=base_time + timedelta(minutes=i),
                    open=price,
                    high=price + 0.5,
                    low=price - 0.5,
                    close=price,
                    volume=100.0,
                )
            )
        for i in range(200):
            price = candles[-1].close + ((i + 1) * 0.2)  # Strong rally
            candles.append(
                Candle(
                    timestamp=base_time + timedelta(minutes=200 + i),
                    open=price - 0.1,
                    high=price + 0.5,
                    low=price - 0.5,
                    close=price,
                    volume=100.0,
                )
            )

        engine = Engine(
            strategy=MACrossover(
                fast_period=5,
                slow_period=10,
                risk_percent=0.5,
                sl_percent=5.0,
                tp_percent=10.0,
            ),
            data_provider=FakeDataProvider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 2, 1, tzinfo=UTC),
        )
        results = await engine.run()
        assert results is not None
        assert len(results.equity_curve) > 0
        # Regime change should force at least 1 crossover → at least 1 trade
        assert results.total_trades >= 1
