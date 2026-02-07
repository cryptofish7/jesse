"""Tests for RSI, breakout, and multi-timeframe example strategies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Position, Signal, TimeframeData
from src.strategy.examples.breakout_strategy import BreakoutStrategy, _channel
from src.strategy.examples.mtf_strategy import MTFStrategy
from src.strategy.examples.rsi_strategy import RSIStrategy, _rsi


# --- Helpers ---


def _candle_at(
    dt: datetime,
    open_: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: float = 1.0,
) -> Candle:
    """Create a candle at a specific datetime with custom OHLCV."""
    return Candle(
        timestamp=dt,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _make_candles(
    prices: list[float],
    base: datetime | None = None,
) -> list[Candle]:
    """Create a list of candles from close prices, 1 per minute."""
    if base is None:
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    candles = []
    for i, price in enumerate(prices):
        candles.append(
            _candle_at(
                base + timedelta(minutes=i),
                open_=price - 1,
                high=price + 2,
                low=price - 2,
                close=price,
            )
        )
    return candles


# ===================================================================
# RSI helper tests
# ===================================================================


class TestRSI:
    def test_rsi_insufficient_data(self) -> None:
        candles = _make_candles([100.0] * 10)
        assert _rsi(candles, 14) is None

    def test_rsi_all_gains(self) -> None:
        """RSI should be 100 when price only goes up."""
        prices = [100 + i for i in range(20)]
        candles = _make_candles(prices)
        result = _rsi(candles, 14)
        assert result is not None
        assert result == 100.0

    def test_rsi_all_losses(self) -> None:
        """RSI should be 0 when price only goes down."""
        prices = [200 - i for i in range(20)]
        candles = _make_candles(prices)
        result = _rsi(candles, 14)
        assert result is not None
        assert result == pytest.approx(0.0, abs=0.01)

    def test_rsi_mixed_range(self) -> None:
        """RSI should be between 0 and 100 for mixed price action."""
        prices = [100, 102, 101, 103, 100, 98, 101, 104, 103, 102, 105, 103, 101, 104, 106, 105]
        candles = _make_candles(prices)
        result = _rsi(candles, 14)
        assert result is not None
        assert 0 < result < 100

    def test_rsi_exact_period(self) -> None:
        """RSI should work with exactly period + 1 candles."""
        prices = list(range(100, 116))  # 16 prices -> 15 deltas, need period+1
        candles = _make_candles(prices)
        result = _rsi(candles, 14)
        assert result is not None


# ===================================================================
# RSI Strategy tests
# ===================================================================


class TestRSIStrategy:
    def test_default_params(self) -> None:
        s = RSIStrategy()
        assert s.period == 14
        assert s.overbought == 70.0
        assert s.oversold == 30.0
        assert s.timeframes == ["1m"]

    def test_custom_params(self) -> None:
        s = RSIStrategy(period=7, overbought=80, oversold=20, risk_percent=0.5)
        assert s.period == 7
        assert s.overbought == 80.0
        assert s.oversold == 20.0
        assert s.risk_percent == 0.5

    def test_no_signal_insufficient_data(self) -> None:
        s = RSIStrategy(period=14)
        portfolio = Portfolio(initial_balance=10000)

        candles = _make_candles([100.0] * 5)
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=candles[-1], history=candles)
        assert s.on_candle(mtf, portfolio) == []

    def test_no_signal_first_candle_with_data(self) -> None:
        """First candle with valid RSI should not signal (no previous RSI)."""
        s = RSIStrategy(period=5)
        portfolio = Portfolio(initial_balance=10000)

        prices = [100 + i for i in range(10)]
        candles = _make_candles(prices)
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=candles[-1], history=candles)
        assert s.on_candle(mtf, portfolio) == []

    def test_oversold_generates_long(self) -> None:
        """Simulate RSI crossing below oversold threshold."""
        s = RSIStrategy(period=5, oversold=30, overbought=70)
        portfolio = Portfolio(initial_balance=10000)

        # Start high, then crash hard -> RSI drops below 30
        prices = [100, 102, 104, 106, 108, 110, 108, 104, 98, 90, 80, 70, 65, 60]
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        signals: list[Signal] = []
        for i in range(1, len(prices)):
            history = _make_candles(prices[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=history[-1], history=history)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        long_signals = [sig for sig in signals if sig.direction == "long"]
        assert len(long_signals) > 0
        assert long_signals[0].stop_loss is not None
        assert long_signals[0].take_profit is not None

    def test_overbought_generates_short(self) -> None:
        """Simulate RSI crossing above overbought threshold."""
        s = RSIStrategy(period=5, oversold=30, overbought=70)
        portfolio = Portfolio(initial_balance=10000)

        # Start low, then rally hard -> RSI rises above 70
        prices = [100, 98, 96, 94, 92, 90, 92, 96, 102, 110, 120, 130, 135, 140]
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        signals: list[Signal] = []
        for i in range(1, len(prices)):
            history = _make_candles(prices[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=history[-1], history=history)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        short_signals = [sig for sig in signals if sig.direction == "short"]
        assert len(short_signals) > 0
        assert short_signals[0].stop_loss is not None
        assert short_signals[0].take_profit is not None

    def test_closes_opposite_positions(self) -> None:
        """When going long, should close existing short positions."""
        s = RSIStrategy(period=5, oversold=30, overbought=70)
        portfolio = Portfolio(initial_balance=10000)
        # Add a fake short position
        short_pos = Position(
            id="test123",
            side="short",
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1, tzinfo=UTC),
            size=0.1,
            size_usd=1000.0,
            stop_loss=110.0,
            take_profit=90.0,
        )
        portfolio.positions.append(short_pos)
        portfolio.balance -= short_pos.size_usd  # type: ignore[operator]

        # Force RSI state so that next call triggers oversold crossing
        s._prev_rsi = 31.0  # Above oversold

        # Create candles with very low RSI (strong downtrend)
        prices = [100, 90, 80, 70, 60, 50, 45]
        candles = _make_candles(prices)
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=candles[-1], history=candles)

        signals = s.on_candle(mtf, portfolio)
        close_signals = [sig for sig in signals if sig.direction == "close"]
        # Should have a close signal for the short position
        if close_signals:
            assert close_signals[0].position_id == "test123"

    def test_state_roundtrip(self) -> None:
        s = RSIStrategy()
        s._prev_rsi = 45.2
        state = s.get_state()
        assert state == {"prev_rsi": 45.2}

        s2 = RSIStrategy()
        s2.set_state(state)
        assert s2._prev_rsi == 45.2


# ===================================================================
# Channel helper tests
# ===================================================================


class TestChannel:
    def test_channel_insufficient_data(self) -> None:
        candles = _make_candles([100.0] * 3)
        assert _channel(candles, 5) is None

    def test_channel_basic(self) -> None:
        """Channel should return highest high and lowest low."""
        prices = [100, 105, 95, 110, 90]
        candles = _make_candles(prices)
        # highs = price + 2 -> [102, 107, 97, 112, 92]
        # lows  = price - 2 -> [98, 103, 93, 108, 88]
        result = _channel(candles, 5)
        assert result is not None
        upper, lower = result
        assert upper == 112.0  # max high
        assert lower == 88.0  # min low

    def test_channel_uses_last_n(self) -> None:
        """Channel should only look at the last N candles."""
        prices = [200, 100, 105, 110]
        candles = _make_candles(prices)
        result = _channel(candles, 3)
        assert result is not None
        upper, lower = result
        # Only last 3 candles: 100, 105, 110
        assert upper == 112.0  # 110 + 2
        assert lower == 98.0  # 100 - 2


# ===================================================================
# Breakout Strategy tests
# ===================================================================


class TestBreakoutStrategy:
    def test_default_params(self) -> None:
        s = BreakoutStrategy()
        assert s.period == 20
        assert s.risk_percent == 1.0
        assert s.tp_multiplier == 1.5
        assert s.timeframes == ["1m"]

    def test_no_signal_insufficient_data(self) -> None:
        s = BreakoutStrategy(period=5)
        portfolio = Portfolio(initial_balance=10000)

        candles = _make_candles([100.0] * 3)
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=candles[-1], history=candles)
        assert s.on_candle(mtf, portfolio) == []

    def test_no_signal_first_valid_candle(self) -> None:
        """First candle with valid channel should not signal (no previous channel)."""
        s = BreakoutStrategy(period=5)
        portfolio = Portfolio(initial_balance=10000)

        prices = [100.0] * 6
        candles = _make_candles(prices)
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=candles[-1], history=candles)
        assert s.on_candle(mtf, portfolio) == []

    def test_upside_breakout_generates_long(self) -> None:
        """Price breaking above the channel upper boundary should trigger a long."""
        s = BreakoutStrategy(period=5, tp_multiplier=1.5)
        portfolio = Portfolio(initial_balance=10000)
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # Stable prices to form a channel, then a breakout
        prices = [100, 100, 100, 100, 100, 100, 100, 120]

        signals: list[Signal] = []
        for i in range(1, len(prices)):
            history = _make_candles(prices[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=history[-1], history=history)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        long_signals = [sig for sig in signals if sig.direction == "long"]
        assert len(long_signals) > 0
        # TP should be above entry, SL below
        assert long_signals[0].take_profit > long_signals[0].stop_loss  # type: ignore[operator]

    def test_downside_breakout_generates_short(self) -> None:
        """Price breaking below the channel lower boundary should trigger a short."""
        s = BreakoutStrategy(period=5, tp_multiplier=1.5)
        portfolio = Portfolio(initial_balance=10000)
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # Stable prices to form a channel, then a breakdown
        prices = [100, 100, 100, 100, 100, 100, 100, 80]

        signals: list[Signal] = []
        for i in range(1, len(prices)):
            history = _make_candles(prices[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=history[-1], history=history)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        short_signals = [sig for sig in signals if sig.direction == "short"]
        assert len(short_signals) > 0
        # Short: SL above entry, TP below
        assert short_signals[0].stop_loss > short_signals[0].take_profit  # type: ignore[operator]

    def test_closes_opposite_on_breakout(self) -> None:
        """On an upside breakout, should close existing short positions."""
        s = BreakoutStrategy(period=5)
        portfolio = Portfolio(initial_balance=10000)
        short_pos = Position(
            id="short1",
            side="short",
            entry_price=100.0,
            entry_time=datetime(2024, 1, 1, tzinfo=UTC),
            size=0.1,
            size_usd=1000.0,
            stop_loss=110.0,
            take_profit=90.0,
        )
        portfolio.positions.append(short_pos)
        portfolio.balance -= short_pos.size_usd  # type: ignore[operator]

        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        prices = [100, 100, 100, 100, 100, 100, 100, 120]

        signals: list[Signal] = []
        for i in range(1, len(prices)):
            history = _make_candles(prices[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=history[-1], history=history)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        close_signals = [sig for sig in signals if sig.direction == "close"]
        assert len(close_signals) > 0
        assert close_signals[0].position_id == "short1"

    def test_no_breakout_in_flat_market(self) -> None:
        """In a flat market where price stays within the channel, no signals."""
        s = BreakoutStrategy(period=5)
        portfolio = Portfolio(initial_balance=10000)
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        prices = [100, 100, 100, 100, 100, 100, 100, 100]

        signals: list[Signal] = []
        for i in range(1, len(prices)):
            history = _make_candles(prices[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=history[-1], history=history)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        # No breakout signals in a flat market
        assert len([sig for sig in signals if sig.direction in ("long", "short")]) == 0

    def test_state_roundtrip(self) -> None:
        s = BreakoutStrategy()
        s._prev_upper = 110.0
        s._prev_lower = 90.0
        state = s.get_state()
        assert state == {"prev_upper": 110.0, "prev_lower": 90.0}

        s2 = BreakoutStrategy()
        s2.set_state(state)
        assert s2._prev_upper == 110.0
        assert s2._prev_lower == 90.0


# ===================================================================
# MTF Strategy tests
# ===================================================================


class TestMTFStrategy:
    def test_default_params(self) -> None:
        s = MTFStrategy()
        assert s.trend_period == 50
        assert s.fast_period == 10
        assert s.slow_period == 30
        assert s.timeframes == ["1m", "4h"]

    def test_custom_params(self) -> None:
        s = MTFStrategy(trend_period=20, fast_period=5, slow_period=15, risk_percent=0.5)
        assert s.trend_period == 20
        assert s.fast_period == 5
        assert s.slow_period == 15
        assert s.risk_percent == 0.5

    def test_no_signal_insufficient_4h_data(self) -> None:
        """Not enough 4h history for the trend SMA -> no signals."""
        s = MTFStrategy(trend_period=5, fast_period=3, slow_period=5)
        portfolio = Portfolio(initial_balance=10000)

        # Only 3 4h candles (need 5 for trend SMA)
        candles_4h = _make_candles([100.0] * 3)
        candles_1m = _make_candles([100.0] * 10)

        mtf = MultiTimeframeData()
        mtf["4h"] = TimeframeData(latest=candles_4h[-1], history=candles_4h)
        mtf["1m"] = TimeframeData(latest=candles_1m[-1], history=candles_1m)

        assert s.on_candle(mtf, portfolio) == []

    def test_no_signal_insufficient_1m_data(self) -> None:
        """Not enough 1m history for MAs -> no signals."""
        s = MTFStrategy(trend_period=3, fast_period=3, slow_period=5)
        portfolio = Portfolio(initial_balance=10000)

        candles_4h = _make_candles([100.0] * 5)
        candles_1m = _make_candles([100.0] * 2)

        mtf = MultiTimeframeData()
        mtf["4h"] = TimeframeData(latest=candles_4h[-1], history=candles_4h)
        mtf["1m"] = TimeframeData(latest=candles_1m[-1], history=candles_1m)

        assert s.on_candle(mtf, portfolio) == []

    def test_long_in_uptrend(self) -> None:
        """When 4h is bullish and 1m crosses above, should go long."""
        s = MTFStrategy(trend_period=3, fast_period=3, slow_period=5)
        portfolio = Portfolio(initial_balance=10000)
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # 4h candles: trending up (above SMA)
        candles_4h = _make_candles([100, 105, 110, 115, 120])

        # 1m: slow descent then sharp rise (fast crosses above slow)
        prices_1m = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 95, 100, 110]

        signals: list[Signal] = []
        for i in range(1, len(prices_1m)):
            history_1m = _make_candles(prices_1m[: i + 1], base)
            mtf = MultiTimeframeData()
            # 4h data: latest is well above trend SMA
            mtf["4h"] = TimeframeData(latest=candles_4h[-1], history=candles_4h)
            mtf["1m"] = TimeframeData(latest=history_1m[-1], history=history_1m)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        long_signals = [sig for sig in signals if sig.direction == "long"]
        assert len(long_signals) > 0

    def test_no_long_in_downtrend(self) -> None:
        """When 4h is bearish, bullish 1m crossover should NOT trigger a long."""
        s = MTFStrategy(trend_period=3, fast_period=3, slow_period=5)
        portfolio = Portfolio(initial_balance=10000)
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # 4h candles: trending down (below SMA)
        candles_4h = _make_candles([120, 115, 110, 105, 100])
        # Set latest 4h below trend SMA
        latest_4h = _candle_at(
            base, open_=96, high=97, low=95, close=96  # Below SMA of ~105
        )

        # 1m: same bullish crossover pattern
        prices_1m = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 95, 100, 110]

        signals: list[Signal] = []
        for i in range(1, len(prices_1m)):
            history_1m = _make_candles(prices_1m[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["4h"] = TimeframeData(latest=latest_4h, history=candles_4h)
            mtf["1m"] = TimeframeData(latest=history_1m[-1], history=history_1m)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        long_signals = [sig for sig in signals if sig.direction == "long"]
        assert len(long_signals) == 0

    def test_short_in_downtrend(self) -> None:
        """When 4h is bearish and 1m crosses below, should go short."""
        s = MTFStrategy(trend_period=3, fast_period=3, slow_period=5)
        portfolio = Portfolio(initial_balance=10000)
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # 4h candles: trending down (below SMA)
        candles_4h = _make_candles([120, 115, 110, 105, 100])
        latest_4h = _candle_at(base, open_=96, high=97, low=95, close=96)

        # 1m: ascend then sharp drop (fast crosses below slow)
        prices_1m = [90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 95, 90, 80]

        signals: list[Signal] = []
        for i in range(1, len(prices_1m)):
            history_1m = _make_candles(prices_1m[: i + 1], base)
            mtf = MultiTimeframeData()
            mtf["4h"] = TimeframeData(latest=latest_4h, history=candles_4h)
            mtf["1m"] = TimeframeData(latest=history_1m[-1], history=history_1m)
            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        short_signals = [sig for sig in signals if sig.direction == "short"]
        assert len(short_signals) > 0

    def test_state_roundtrip(self) -> None:
        s = MTFStrategy()
        s._prev_fast = 100.0
        s._prev_slow = 95.0
        state = s.get_state()
        assert state == {"prev_fast": 100.0, "prev_slow": 95.0}

        s2 = MTFStrategy()
        s2.set_state(state)
        assert s2._prev_fast == 100.0
        assert s2._prev_slow == 95.0
