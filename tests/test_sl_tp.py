"""Tests for SL/TP monitoring and drill-down resolution."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.types import Candle, Position
from src.execution.sl_tp import SLTPMonitor

# --- Helpers ---


def _make_position(
    side: str = "long",
    entry_price: float = 100.0,
    stop_loss: float = 90.0,
    take_profit: float = 110.0,
) -> Position:
    return Position(
        id="test-pos-001",
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        entry_time=datetime(2024, 1, 1, tzinfo=UTC),
        size=1.0,
        size_usd=100.0,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def _make_candle(
    low: float = 95.0,
    high: float = 105.0,
    open_: float = 100.0,
    close: float = 102.0,
) -> Candle:
    return Candle(
        timestamp=datetime(2024, 1, 1, 0, 0, tzinfo=UTC),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
    )


# --- SLTPMonitor.check() tests ---


class TestSLTPCheck:
    def setup_method(self) -> None:
        self.monitor = SLTPMonitor()

    def test_long_sl_hit(self) -> None:
        pos = _make_position(side="long", stop_loss=95.0, take_profit=110.0)
        candle = _make_candle(low=94.0, high=105.0)  # Low breaches SL, high doesn't reach TP
        assert self.monitor.check(pos, candle) == "stop_loss"

    def test_long_tp_hit(self) -> None:
        pos = _make_position(side="long", stop_loss=90.0, take_profit=106.0)
        candle = _make_candle(low=95.0, high=107.0)  # High reaches TP, low doesn't breach SL
        assert self.monitor.check(pos, candle) == "take_profit"

    def test_long_neither_hit(self) -> None:
        pos = _make_position(side="long", stop_loss=90.0, take_profit=110.0)
        candle = _make_candle(low=95.0, high=105.0)  # Within SL/TP range
        assert self.monitor.check(pos, candle) is None

    def test_long_both_hit_no_drill_data(self) -> None:
        pos = _make_position(side="long", stop_loss=95.0, take_profit=105.0)
        candle = _make_candle(low=94.0, high=106.0)  # Breaches both
        # No available_candles — conservative fallback
        assert self.monitor.check(pos, candle) == "stop_loss"

    def test_short_sl_hit(self) -> None:
        pos = _make_position(side="short", entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        candle = _make_candle(low=95.0, high=106.0)  # High breaches SL, low doesn't reach TP
        assert self.monitor.check(pos, candle) == "stop_loss"

    def test_short_tp_hit(self) -> None:
        pos = _make_position(side="short", entry_price=100.0, stop_loss=110.0, take_profit=95.0)
        candle = _make_candle(low=94.0, high=105.0)  # Low reaches TP, high doesn't breach SL
        assert self.monitor.check(pos, candle) == "take_profit"

    def test_short_neither_hit(self) -> None:
        pos = _make_position(side="short", entry_price=100.0, stop_loss=110.0, take_profit=90.0)
        candle = _make_candle(low=95.0, high=105.0)  # Within range
        assert self.monitor.check(pos, candle) is None

    def test_short_both_hit_conservative(self) -> None:
        pos = _make_position(side="short", entry_price=100.0, stop_loss=105.0, take_profit=95.0)
        candle = _make_candle(low=94.0, high=106.0)  # Both breached
        # At 1m (default), conservative fallback
        assert self.monitor.check(pos, candle) == "stop_loss"

    def test_sl_at_exact_boundary(self) -> None:
        pos = _make_position(side="long", stop_loss=95.0, take_profit=110.0)
        candle = _make_candle(low=95.0, high=105.0)  # Low exactly at SL
        assert self.monitor.check(pos, candle) == "stop_loss"

    def test_tp_at_exact_boundary(self) -> None:
        pos = _make_position(side="long", stop_loss=90.0, take_profit=105.0)
        candle = _make_candle(low=95.0, high=105.0)  # High exactly at TP
        assert self.monitor.check(pos, candle) == "take_profit"


# --- SLTPMonitor.resolve() drill-down tests ---


class TestSLTPResolve:
    def setup_method(self) -> None:
        self.monitor = SLTPMonitor()

    def test_resolve_sl_first_in_sub_candles(self) -> None:
        """4h candle has both hit. 1h sub-candle hits only SL first."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)  # Both hit

        # 1h sub-candles: first one hits SL only
        sub_candles = {
            "1h": [
                _make_candle(low=94.0, high=100.0),  # SL hit, TP not hit
                _make_candle(low=96.0, high=109.0),  # TP hit
            ]
        }

        result = self.monitor.resolve(pos, parent, sub_candles, current_timeframe="4h")
        assert result == "stop_loss"

    def test_resolve_tp_first_in_sub_candles(self) -> None:
        """4h candle has both hit. 1h sub-candle hits only TP first."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)

        sub_candles = {
            "1h": [
                _make_candle(low=96.0, high=109.0),  # TP hit, SL not hit
                _make_candle(low=94.0, high=100.0),  # SL hit
            ]
        }

        result = self.monitor.resolve(pos, parent, sub_candles, current_timeframe="4h")
        assert result == "take_profit"

    def test_resolve_recursive_to_lower_tf(self) -> None:
        """4h both hit, 1h both hit, 15m resolves to TP."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)

        sub_candles = {
            # 1h: both hit on first candle
            "1h": [_make_candle(low=94.0, high=109.0)],
            # 15m: first candle hits TP only
            "15m": [
                _make_candle(low=96.0, high=109.0),  # TP hit only
            ],
        }

        result = self.monitor.resolve(pos, parent, sub_candles, current_timeframe="4h")
        assert result == "take_profit"

    def test_resolve_fallback_at_1m(self) -> None:
        """Both hit all the way down to 1m — conservative SL."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)

        sub_candles = {
            "1h": [_make_candle(low=94.0, high=109.0)],
            "15m": [_make_candle(low=94.0, high=109.0)],
            "5m": [_make_candle(low=94.0, high=109.0)],
            "1m": [_make_candle(low=94.0, high=109.0)],  # Both hit at 1m
        }

        result = self.monitor.resolve(pos, parent, sub_candles, current_timeframe="4h")
        assert result == "stop_loss"

    def test_resolve_no_sub_candles_available(self) -> None:
        """No lower-TF data — conservative SL."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)

        result = self.monitor.resolve(pos, parent, {}, current_timeframe="4h")
        assert result == "stop_loss"

    def test_resolve_empty_sub_candle_list(self) -> None:
        """Lower-TF key exists but empty list — conservative SL."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)

        result = self.monitor.resolve(pos, parent, {"1h": []}, current_timeframe="4h")
        assert result == "stop_loss"

    def test_resolve_sub_candle_neither_hit_continues(self) -> None:
        """First sub-candle hits neither, second hits SL."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        parent = _make_candle(low=94.0, high=109.0)

        sub_candles = {
            "1h": [
                _make_candle(low=96.0, high=107.0),  # Neither hit
                _make_candle(low=94.0, high=107.0),  # SL hit only
            ]
        }

        result = self.monitor.resolve(pos, parent, sub_candles, current_timeframe="4h")
        assert result == "stop_loss"

    def test_resolve_short_position_drill_down(self) -> None:
        """Short position: drill-down resolves to TP."""
        pos = _make_position(side="short", entry_price=100.0, stop_loss=108.0, take_profit=92.0)
        parent = _make_candle(low=91.0, high=109.0)  # Both hit for short

        sub_candles = {
            "1h": [
                _make_candle(low=91.0, high=107.0),  # TP hit (low <= 92), SL not hit
            ]
        }

        result = self.monitor.resolve(pos, parent, sub_candles, current_timeframe="4h")
        assert result == "take_profit"

    def test_check_with_available_candles_resolves(self) -> None:
        """check() with available_candles does drill-down automatically."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        candle = _make_candle(low=94.0, high=109.0)  # Both hit

        available = {
            "1h": [_make_candle(low=96.0, high=109.0)],  # TP first
        }

        result = self.monitor.check(
            pos, candle, available_candles=available, current_timeframe="4h"
        )
        assert result == "take_profit"

    def test_check_at_1m_both_hit_with_available_candles(self) -> None:
        """check() at 1m with both hit and available_candles falls back to SL."""
        pos = _make_position(side="long", stop_loss=95.0, take_profit=108.0)
        candle = _make_candle(low=94.0, high=109.0)  # Both hit

        # Even with available_candles, at 1m there's nowhere to drill
        available: dict[str, list] = {}

        result = self.monitor.check(
            pos, candle, available_candles=available, current_timeframe="1m"
        )
        assert result == "stop_loss"
