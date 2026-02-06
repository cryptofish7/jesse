"""Tests for analysis metrics, charts, and BacktestResults integration."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta

import pytest

from src.analysis.charts import plot_equity_curve, plot_trades
from src.analysis.metrics import (
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_total_return,
    calculate_win_rate,
)
from src.core.engine import BacktestResults, EquityPoint
from src.core.types import Candle, Trade

# --- Test helpers ---

_BASE_TIME = datetime(2024, 1, 1, tzinfo=UTC)


def _make_trade(
    pnl: float,
    *,
    id: str = "t1",
    side: str = "long",
    entry_price: float = 100.0,
    exit_price: float | None = None,
    entry_time: datetime | None = None,
    exit_time: datetime | None = None,
    size: float = 1.0,
    size_usd: float = 100.0,
    pnl_percent: float | None = None,
    exit_reason: str = "signal",
) -> Trade:
    """Create a Trade with sensible defaults, only overriding what you need."""
    return Trade(
        id=id,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        exit_price=exit_price if exit_price is not None else entry_price + pnl,
        entry_time=entry_time or _BASE_TIME,
        exit_time=exit_time or _BASE_TIME + timedelta(hours=1),
        size=size,
        size_usd=size_usd,
        pnl=pnl,
        pnl_percent=pnl_percent if pnl_percent is not None else (pnl / entry_price) * 100,
        exit_reason=exit_reason,  # type: ignore[arg-type]
    )


def _make_equity_point(equity: float, minutes_offset: int = 0) -> EquityPoint:
    """Create an EquityPoint at a given offset from the base time."""
    return EquityPoint(
        timestamp=_BASE_TIME + timedelta(minutes=minutes_offset),
        equity=equity,
    )


def _make_candle(
    close: float,
    minutes_offset: int = 0,
    *,
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: float = 100.0,
) -> Candle:
    """Create a Candle with sensible defaults."""
    o = open_price if open_price is not None else close - 0.5
    h = high if high is not None else close + 1.0
    lo = low if low is not None else close - 1.0
    return Candle(
        timestamp=_BASE_TIME + timedelta(minutes=minutes_offset),
        open=o,
        high=h,
        low=lo,
        close=close,
        volume=volume,
    )


# --- Metric tests ---


class TestWinRate:
    def test_basic(self) -> None:
        """3 wins, 2 losses -> 0.6."""
        trades = [
            _make_trade(10, id="t1"),
            _make_trade(5, id="t2"),
            _make_trade(3, id="t3"),
            _make_trade(-8, id="t4"),
            _make_trade(-2, id="t5"),
        ]
        assert calculate_win_rate(trades) == pytest.approx(0.6)

    def test_all_wins(self) -> None:
        trades = [_make_trade(10, id="t1"), _make_trade(5, id="t2")]
        assert calculate_win_rate(trades) == pytest.approx(1.0)

    def test_all_losses(self) -> None:
        trades = [_make_trade(-10, id="t1"), _make_trade(-5, id="t2")]
        assert calculate_win_rate(trades) == pytest.approx(0.0)

    def test_with_breakeven(self) -> None:
        """Break-even (pnl=0) is NOT a win, counts in denominator."""
        trades = [
            _make_trade(10, id="t1"),
            _make_trade(0, id="t2"),
            _make_trade(-5, id="t3"),
        ]
        # 1 win out of 3
        assert calculate_win_rate(trades) == pytest.approx(1 / 3)

    def test_empty(self) -> None:
        assert calculate_win_rate([]) == 0.0


class TestProfitFactor:
    def test_basic(self) -> None:
        """350 profit / 125 loss = 2.8."""
        trades = [
            _make_trade(200, id="t1"),
            _make_trade(150, id="t2"),
            _make_trade(-75, id="t3"),
            _make_trade(-50, id="t4"),
        ]
        assert calculate_profit_factor(trades) == pytest.approx(2.8)

    def test_no_losses(self) -> None:
        trades = [_make_trade(10, id="t1"), _make_trade(5, id="t2")]
        assert calculate_profit_factor(trades) == float("inf")

    def test_no_wins(self) -> None:
        trades = [_make_trade(-10, id="t1"), _make_trade(-5, id="t2")]
        assert calculate_profit_factor(trades) == 0.0

    def test_empty(self) -> None:
        assert calculate_profit_factor([]) == 0.0

    def test_breakeven_trades(self) -> None:
        """Break-even trades (pnl=0) should be excluded from both gross profit and loss."""
        trades = [
            _make_trade(10, id="t1"),
            _make_trade(0, id="t2"),
            _make_trade(0, id="t3"),
            _make_trade(-5, id="t4"),
        ]
        # gross_profit=10, gross_loss=5 -> 2.0
        assert calculate_profit_factor(trades) == pytest.approx(2.0)


class TestTotalReturn:
    def test_positive(self) -> None:
        assert calculate_total_return(10000, 12000) == pytest.approx(0.2)

    def test_negative(self) -> None:
        assert calculate_total_return(10000, 8000) == pytest.approx(-0.2)

    def test_zero_initial(self) -> None:
        assert calculate_total_return(0, 5000) == 0.0


class TestMaxDrawdown:
    def test_basic(self) -> None:
        """Known curve: peak 110, trough 90, dd = 20/110."""
        curve = [
            _make_equity_point(100, 0),
            _make_equity_point(110, 1),
            _make_equity_point(90, 2),
            _make_equity_point(120, 3),
        ]
        assert calculate_max_drawdown(curve) == pytest.approx(20 / 110)

    def test_empty(self) -> None:
        assert calculate_max_drawdown([]) == 0.0

    def test_monotonic_increase(self) -> None:
        curve = [
            _make_equity_point(100, 0),
            _make_equity_point(105, 1),
            _make_equity_point(110, 2),
            _make_equity_point(120, 3),
        ]
        assert calculate_max_drawdown(curve) == pytest.approx(0.0)

    def test_single_point(self) -> None:
        curve = [_make_equity_point(100, 0)]
        assert calculate_max_drawdown(curve) == 0.0

    def test_monotonic_decrease(self) -> None:
        """Curve that only goes down: drawdown should equal total decline from start."""
        curve = [
            _make_equity_point(100, 0),
            _make_equity_point(90, 1),
            _make_equity_point(80, 2),
            _make_equity_point(70, 3),
        ]
        # Peak is 100, trough is 70 -> dd = 30/100 = 0.30
        assert calculate_max_drawdown(curve) == pytest.approx(0.30)


class TestSharpeRatio:
    def test_empty(self) -> None:
        assert calculate_sharpe_ratio([]) == 0.0

    def test_single_point(self) -> None:
        curve = [_make_equity_point(100, 0)]
        assert calculate_sharpe_ratio(curve) == 0.0

    def test_constant_equity(self) -> None:
        """Zero std dev -> 0.0."""
        curve = [_make_equity_point(100, i) for i in range(10)]
        assert calculate_sharpe_ratio(curve) == 0.0

    def test_positive_returns(self) -> None:
        """Steadily increasing equity should give a positive Sharpe."""
        curve = [_make_equity_point(100 + i, i) for i in range(50)]
        result = calculate_sharpe_ratio(curve)
        assert result > 0

    def test_negative_returns(self) -> None:
        """Steadily decreasing equity should give a negative Sharpe."""
        curve = [_make_equity_point(100 - i * 0.5, i) for i in range(50)]
        result = calculate_sharpe_ratio(curve)
        assert result < 0


# --- Chart tests ---


class TestPlotEquityCurve:
    def test_creates_file(self, tmp_path) -> None:
        curve = [
            _make_equity_point(10000, 0),
            _make_equity_point(10500, 1),
            _make_equity_point(10200, 2),
            _make_equity_point(10800, 3),
        ]
        out = tmp_path / "equity.html"
        plot_equity_curve(curve, out)
        assert out.exists()
        content = out.read_text()
        assert "plotly" in content.lower()

    def test_empty_does_not_crash(self, tmp_path) -> None:
        out = tmp_path / "empty_equity.html"
        plot_equity_curve([], out)
        assert out.exists()
        content = out.read_text()
        assert "No data" in content


class TestPlotTrades:
    def test_creates_file(self, tmp_path) -> None:
        candles = [_make_candle(100 + i * 0.5, i) for i in range(20)]
        trades = [
            _make_trade(
                10,
                id="t1",
                entry_price=100.0,
                exit_price=110.0,
                entry_time=_BASE_TIME + timedelta(minutes=2),
                exit_time=_BASE_TIME + timedelta(minutes=15),
                exit_reason="take_profit",
            ),
        ]
        out = tmp_path / "trades.html"
        plot_trades(candles, trades, out)
        assert out.exists()
        content = out.read_text()
        assert "plotly" in content.lower()

    def test_empty_trades(self, tmp_path) -> None:
        """Empty trades should create chart with candles only."""
        candles = [_make_candle(100 + i, i) for i in range(10)]
        out = tmp_path / "no_trades.html"
        plot_trades(candles, [], out)
        assert out.exists()

    def test_empty_candles(self, tmp_path) -> None:
        """Empty candles should create chart with 'No data' annotation."""
        out = tmp_path / "no_candles.html"
        plot_trades([], [], out)
        assert out.exists()
        content = out.read_text()
        assert "No data" in content


# --- BacktestResults integration tests ---


def _make_results(
    trades: list[Trade] | None = None,
    equity_curve: list[EquityPoint] | None = None,
    initial_balance: float = 10_000.0,
    final_equity: float = 10_000.0,
) -> BacktestResults:
    return BacktestResults(
        trades=trades or [],
        equity_curve=equity_curve or [],
        start_time=_BASE_TIME,
        end_time=_BASE_TIME + timedelta(days=1),
        initial_balance=initial_balance,
        final_equity=final_equity,
    )


class TestBacktestResultsExportTrades:
    def test_export_trades(self, tmp_path) -> None:
        trades = [
            _make_trade(50, id="t1", side="long", exit_reason="take_profit"),
            _make_trade(-20, id="t2", side="short", exit_reason="stop_loss"),
        ]
        results = _make_results(trades=trades)
        out = tmp_path / "trades.csv"
        results.export_trades(out)

        assert out.exists()
        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2

        # Verify expected columns exist
        expected_cols = {
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
        }
        assert set(rows[0].keys()) == expected_cols

        # Verify data
        assert rows[0]["id"] == "t1"
        assert rows[0]["side"] == "long"
        assert float(rows[0]["pnl"]) == pytest.approx(50)
        assert rows[0]["exit_reason"] == "take_profit"

        assert rows[1]["id"] == "t2"
        assert float(rows[1]["pnl"]) == pytest.approx(-20)
        assert rows[1]["exit_reason"] == "stop_loss"

    def test_export_trades_empty(self, tmp_path) -> None:
        """Empty trades should produce CSV with headers only."""
        results = _make_results()
        out = tmp_path / "empty_trades.csv"
        results.export_trades(out)

        assert out.exists()
        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 0
        # Re-read to check headers are present
        with open(out) as f:
            header_line = f.readline().strip()
        assert "id" in header_line
        assert "pnl" in header_line


class TestBacktestResultsPlotMethods:
    def test_plot_equity_curve(self, tmp_path) -> None:
        curve = [_make_equity_point(10000 + i * 10, i) for i in range(5)]
        results = _make_results(equity_curve=curve)
        out = tmp_path / "eq.html"
        results.plot_equity_curve(out)
        assert out.exists()

    def test_plot_trades(self, tmp_path) -> None:
        candles = [_make_candle(100, i) for i in range(10)]
        trades = [_make_trade(5, id="t1", exit_reason="signal")]
        results = _make_results(trades=trades)
        out = tmp_path / "trades_chart.html"
        results.plot_trades(candles, out)
        assert out.exists()
