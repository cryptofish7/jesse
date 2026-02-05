"""Tests for Strategy interface, TimeframeAggregator, and example strategies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.portfolio import Portfolio
from src.core.timeframe import (
    TimeframeAggregator,
    get_lower_timeframe,
    get_timeframe_minutes,
    is_timeframe_complete,
)
from src.core.types import Candle, MultiTimeframeData, Signal, TimeframeData
from src.strategy.base import Strategy
from src.strategy.examples.ma_crossover import MACrossover, _sma

# --- Helpers ---


def _candle(
    minute: int,
    base_time: datetime | None = None,
    price: float = 100_000.0,
    volume: float = 1.0,
) -> Candle:
    """Create a candle at a specific minute offset."""
    if base_time is None:
        base_time = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    ts = base_time + timedelta(minutes=minute)
    return Candle(
        timestamp=ts,
        open=price,
        high=price + 10,
        low=price - 10,
        close=price + 5,
        volume=volume,
    )


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


# --- Timeframe utility tests ---


class TestGetTimeframeMinutes:
    def test_known_timeframes(self) -> None:
        assert get_timeframe_minutes("1m") == 1
        assert get_timeframe_minutes("5m") == 5
        assert get_timeframe_minutes("15m") == 15
        assert get_timeframe_minutes("1h") == 60
        assert get_timeframe_minutes("4h") == 240
        assert get_timeframe_minutes("1d") == 1440
        assert get_timeframe_minutes("1w") == 10080

    def test_unknown_timeframe_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown timeframe"):
            get_timeframe_minutes("2m")


class TestGetLowerTimeframe:
    def test_lower_timeframes(self) -> None:
        assert get_lower_timeframe("5m") == "1m"
        assert get_lower_timeframe("15m") == "5m"
        assert get_lower_timeframe("1h") == "15m"
        assert get_lower_timeframe("4h") == "1h"
        assert get_lower_timeframe("1d") == "4h"
        assert get_lower_timeframe("1w") == "1d"

    def test_lowest_returns_none(self) -> None:
        assert get_lower_timeframe("1m") is None

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown timeframe"):
            get_lower_timeframe("3h")


class TestIsTimeframeComplete:
    def test_5m_boundaries(self) -> None:
        # Minute 4 (0-indexed) completes a 5m candle
        assert is_timeframe_complete("5m", datetime(2024, 1, 1, 0, 4, tzinfo=UTC))
        assert is_timeframe_complete("5m", datetime(2024, 1, 1, 0, 9, tzinfo=UTC))
        assert is_timeframe_complete("5m", datetime(2024, 1, 1, 0, 14, tzinfo=UTC))
        # Minute 3 does not
        assert not is_timeframe_complete("5m", datetime(2024, 1, 1, 0, 3, tzinfo=UTC))

    def test_1h_boundaries(self) -> None:
        # Minute 59 completes an hour
        assert is_timeframe_complete("1h", datetime(2024, 1, 1, 0, 59, tzinfo=UTC))
        assert is_timeframe_complete("1h", datetime(2024, 1, 1, 1, 59, tzinfo=UTC))
        assert not is_timeframe_complete("1h", datetime(2024, 1, 1, 0, 58, tzinfo=UTC))

    def test_4h_boundaries(self) -> None:
        # 4h completes at 3:59, 7:59, 11:59, etc.
        assert is_timeframe_complete("4h", datetime(2024, 1, 1, 3, 59, tzinfo=UTC))
        assert is_timeframe_complete("4h", datetime(2024, 1, 1, 7, 59, tzinfo=UTC))
        assert not is_timeframe_complete("4h", datetime(2024, 1, 1, 2, 59, tzinfo=UTC))

    def test_1d_boundaries(self) -> None:
        # Daily completes at 23:59
        assert is_timeframe_complete("1d", datetime(2024, 1, 1, 23, 59, tzinfo=UTC))
        assert not is_timeframe_complete("1d", datetime(2024, 1, 1, 22, 59, tzinfo=UTC))

    def test_1w_boundaries(self) -> None:
        # Weekly: completes at Sunday 23:59 UTC (Monday 00:00 boundary)
        # 2024-01-07 is a Sunday
        assert is_timeframe_complete("1w", datetime(2024, 1, 7, 23, 59, tzinfo=UTC))
        # Saturday 23:59 should NOT complete
        assert not is_timeframe_complete("1w", datetime(2024, 1, 6, 23, 59, tzinfo=UTC))
        # Wednesday 23:59 should NOT complete (was a bug — epoch alignment)
        assert not is_timeframe_complete("1w", datetime(2024, 1, 3, 23, 59, tzinfo=UTC))
        # Another Sunday
        assert is_timeframe_complete("1w", datetime(2024, 1, 14, 23, 59, tzinfo=UTC))

    def test_1m_always_complete(self) -> None:
        # Every minute is a complete 1m candle
        assert is_timeframe_complete("1m", datetime(2024, 1, 1, 0, 0, tzinfo=UTC))
        assert is_timeframe_complete("1m", datetime(2024, 1, 1, 0, 37, tzinfo=UTC))


# --- TimeframeAggregator tests ---


class TestTimeframeAggregator:
    def test_1m_only(self) -> None:
        agg = TimeframeAggregator(timeframes=["1m"])
        c1 = _candle(0)
        c2 = _candle(1)

        mtf1 = agg.update(c1)
        assert "1m" in mtf1
        assert mtf1["1m"].latest == c1
        assert len(mtf1["1m"].history) == 1

        mtf2 = agg.update(c2)
        assert mtf2["1m"].latest == c2
        assert len(mtf2["1m"].history) == 2

    def test_5m_aggregation(self) -> None:
        agg = TimeframeAggregator(timeframes=["1m", "5m"])

        # Feed 5 candles (minutes 0-4)
        for i in range(5):
            price = 100 + i
            mtf = agg.update(
                _candle_at(
                    datetime(2024, 1, 1, 0, i, tzinfo=UTC),
                    open_=price,
                    high=price + 10,
                    low=price - 10,
                    close=price + 5,
                    volume=1.0,
                )
            )

        # After minute 4, a 5m candle should be complete
        assert len(mtf["5m"].history) == 1
        completed_5m = mtf["5m"].history[0]
        assert completed_5m.open == 100  # First candle's open
        assert completed_5m.close == 109  # Last candle's close (104 + 5)
        assert completed_5m.volume == 5.0  # Sum of volumes

    def test_in_progress_candle_as_latest(self) -> None:
        agg = TimeframeAggregator(timeframes=["1m", "5m"])

        # Feed 3 candles (minutes 0-2) — 5m candle not yet complete
        for i in range(3):
            mtf = agg.update(
                _candle_at(
                    datetime(2024, 1, 1, 0, i, tzinfo=UTC),
                    close=100 + i,
                )
            )

        # 5m latest should be the in-progress candle, not yet in history
        assert len(mtf["5m"].history) == 0
        assert mtf["5m"].latest.close == 102  # Latest 1m close

    def test_warm_up(self) -> None:
        agg = TimeframeAggregator(timeframes=["1m", "5m"])

        # Create 10 minutes of candles
        candles = [_candle_at(datetime(2024, 1, 1, 0, i, tzinfo=UTC)) for i in range(10)]
        agg.warm_up(candles)

        # Should have 2 completed 5m candles (0-4 and 5-9)
        assert len(agg.get_history("5m")) == 2
        assert len(agg.get_history("1m")) == 10

    def test_max_history_trimming(self) -> None:
        agg = TimeframeAggregator(timeframes=["1m"], max_history=5)

        for i in range(10):
            agg.update(_candle(i))

        assert len(agg.get_history("1m")) == 5

    def test_unknown_timeframe_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown timeframe"):
            TimeframeAggregator(timeframes=["2m"])

    def test_multiple_5m_completions(self) -> None:
        """Test that multiple 5m periods each produce a completed candle."""
        agg = TimeframeAggregator(timeframes=["1m", "5m"])

        for i in range(15):
            mtf = agg.update(_candle_at(datetime(2024, 1, 1, 0, i, tzinfo=UTC)))

        # 3 complete 5m candles (0-4, 5-9, 10-14)
        assert len(mtf["5m"].history) == 3

    def test_4h_aggregation(self) -> None:
        """Test 4h aggregation over 240 1m candles."""
        agg = TimeframeAggregator(timeframes=["1m", "4h"])

        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        for i in range(240):
            mtf = agg.update(
                _candle_at(
                    base + timedelta(minutes=i),
                    open_=100.0,
                    high=110.0,
                    low=90.0,
                    close=105.0,
                    volume=1.0,
                )
            )

        # One complete 4h candle (0:00 - 3:59)
        assert len(mtf["4h"].history) == 1
        assert mtf["4h"].history[0].volume == 240.0


# --- Strategy ABC tests ---


class TestStrategyABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            Strategy()  # type: ignore[abstract]

    def test_concrete_strategy(self) -> None:
        class Dummy(Strategy):
            def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
                return []

        s = Dummy()
        assert s.timeframes == ["1m"]
        assert s.get_state() == {}
        s.set_state({"foo": "bar"})  # Should not raise

    def test_on_init_is_optional(self) -> None:
        class Dummy(Strategy):
            def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
                return []

        s = Dummy()
        # on_init should exist and be callable without error
        mtf = MultiTimeframeData()
        s.on_init(mtf)


# --- SMA helper tests ---


class TestSMA:
    def test_sma_basic(self) -> None:
        candles = [_candle(i, price=float(100 + i)) for i in range(5)]
        # Closes: 105, 106, 107, 108, 109
        result = _sma(candles, 5)
        assert result == pytest.approx(107.0)

    def test_sma_insufficient_data(self) -> None:
        candles = [_candle(0)]
        assert _sma(candles, 5) is None


# --- MACrossover strategy tests ---


class TestMACrossover:
    def test_default_params(self) -> None:
        s = MACrossover()
        assert s.fast_period == 10
        assert s.slow_period == 30
        assert s.risk_percent == 1.0
        assert s.timeframes == ["1m"]

    def test_custom_params(self) -> None:
        s = MACrossover(fast_period=5, slow_period=20, risk_percent=0.5)
        assert s.fast_period == 5
        assert s.slow_period == 20
        assert s.risk_percent == 0.5

    def test_no_signal_insufficient_history(self) -> None:
        s = MACrossover(fast_period=3, slow_period=5)
        portfolio = Portfolio(initial_balance=10000)

        # Only 2 candles — not enough for slow_period=5
        history = [_candle(i) for i in range(2)]
        mtf = MultiTimeframeData()
        mtf["1m"] = TimeframeData(latest=_candle(2), history=history)
        signals = s.on_candle(mtf, portfolio)
        assert signals == []

    def test_crossover_generates_long_signal(self) -> None:
        s = MACrossover(fast_period=3, slow_period=5, sl_percent=2.0, tp_percent=4.0)
        portfolio = Portfolio(initial_balance=10000)

        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # Build history where fast MA is below slow MA, then crosses above
        # Prices: slow descent then sharp rise
        prices = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 95, 100, 110]

        signals = []
        for i, price in enumerate(prices):
            candle = _candle_at(
                base + timedelta(minutes=i),
                open_=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1.0,
            )
            # Build history from all candles up to this point (excluding current)
            history_candles = []
            for j in range(i):
                history_candles.append(
                    _candle_at(
                        base + timedelta(minutes=j),
                        open_=prices[j],
                        high=prices[j] + 1,
                        low=prices[j] - 1,
                        close=prices[j],
                        volume=1.0,
                    )
                )

            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=candle, history=history_candles)

            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        # Should have generated at least one long signal
        long_signals = [s for s in signals if s.direction == "long"]
        assert len(long_signals) > 0
        assert long_signals[0].stop_loss is not None
        assert long_signals[0].take_profit is not None

    def test_crossover_generates_short_signal(self) -> None:
        s = MACrossover(fast_period=3, slow_period=5, sl_percent=2.0, tp_percent=4.0)
        portfolio = Portfolio(initial_balance=10000)

        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

        # Prices: ascend then sharp drop — fast MA crosses below slow MA
        prices = [90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 95, 90, 80]

        signals: list[Signal] = []
        for i, price in enumerate(prices):
            candle = _candle_at(
                base + timedelta(minutes=i),
                open_=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=1.0,
            )
            history_candles = [
                _candle_at(
                    base + timedelta(minutes=j),
                    open_=prices[j],
                    high=prices[j] + 1,
                    low=prices[j] - 1,
                    close=prices[j],
                    volume=1.0,
                )
                for j in range(i)
            ]

            mtf = MultiTimeframeData()
            mtf["1m"] = TimeframeData(latest=candle, history=history_candles)

            result = s.on_candle(mtf, portfolio)
            signals.extend(result)

        short_signals = [s for s in signals if s.direction == "short"]
        assert len(short_signals) > 0
        assert short_signals[0].stop_loss is not None
        assert short_signals[0].take_profit is not None
        # Short SL should be above entry, TP below
        assert short_signals[0].stop_loss > short_signals[0].take_profit

    def test_state_roundtrip(self) -> None:
        s = MACrossover()
        s._prev_fast = 100.0
        s._prev_slow = 95.0

        state = s.get_state()
        assert state == {"prev_fast": 100.0, "prev_slow": 95.0}

        s2 = MACrossover()
        s2.set_state(state)
        assert s2._prev_fast == 100.0
        assert s2._prev_slow == 95.0
