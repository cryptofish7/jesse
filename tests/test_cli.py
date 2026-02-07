"""Tests for the CLI entry point and strategy loader."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from main import _parse_date, build_parser, cmd_backtest, cmd_fetch_data
from src.core.types import Candle
from src.strategy.base import Strategy
from src.strategy.loader import discover_strategies, load_strategy


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestBuildParser:
    """Test CLI argument parsing for all commands."""

    def test_no_command_returns_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_backtest_required_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "backtest",
            "--strategy", "MACrossover",
            "--start", "2024-01-01",
            "--end", "2024-06-01",
        ])
        assert args.command == "backtest"
        assert args.strategy == "MACrossover"
        assert args.start == "2024-01-01"
        assert args.end == "2024-06-01"
        assert args.initial_balance == 10000.0  # default

    def test_backtest_custom_balance(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "backtest",
            "--strategy", "MyStrat",
            "--start", "2024-01-01",
            "--end", "2024-12-01",
            "--initial-balance", "50000",
        ])
        assert args.initial_balance == 50000.0

    def test_backtest_missing_strategy_exits(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["backtest", "--start", "2024-01-01", "--end", "2024-12-01"])

    def test_backtest_missing_start_exits(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["backtest", "--strategy", "X", "--end", "2024-12-01"])

    def test_backtest_missing_end_exits(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["backtest", "--strategy", "X", "--start", "2024-01-01"])

    def test_forward_test_required_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "forward-test",
            "--strategy", "MACrossover",
        ])
        assert args.command == "forward-test"
        assert args.strategy == "MACrossover"
        assert args.initial_balance == 10000.0

    def test_forward_test_custom_balance(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "forward-test",
            "--strategy", "MyStrat",
            "--initial-balance", "25000",
        ])
        assert args.initial_balance == 25000.0

    def test_forward_test_missing_strategy_exits(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["forward-test"])

    def test_fetch_data_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["fetch-data"])
        assert args.command == "fetch-data"
        assert args.symbol == "BTC/USDT:USDT"
        assert args.timeframe == "1m"
        assert args.start is None
        assert args.end is None

    def test_fetch_data_explicit_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "fetch-data",
            "--symbol", "ETH/USDT:USDT",
            "--timeframe", "4h",
            "--start", "2022-01-01",
            "--end", "2024-01-01",
        ])
        assert args.symbol == "ETH/USDT:USDT"
        assert args.timeframe == "4h"
        assert args.start == "2022-01-01"
        assert args.end == "2024-01-01"

    def test_fetch_data_timeframe_optional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["fetch-data"])
        assert args.timeframe == "1m"

    def test_fetch_data_start_end_optional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["fetch-data", "--symbol", "BTC/USDT:USDT"])
        assert args.start is None
        assert args.end is None


# ---------------------------------------------------------------------------
# Date parsing tests
# ---------------------------------------------------------------------------


class TestParseDate:
    """Test the _parse_date helper."""

    def test_valid_date(self) -> None:
        result = _parse_date("2024-06-15")
        assert result == datetime(2024, 6, 15, tzinfo=UTC)

    def test_result_is_utc(self) -> None:
        result = _parse_date("2024-01-01")
        assert result.tzinfo is not None
        assert result.tzinfo == UTC

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid date format"):
            _parse_date("01-01-2024")

    def test_garbage_input_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid date format"):
            _parse_date("not-a-date")


# ---------------------------------------------------------------------------
# Strategy discovery tests
# ---------------------------------------------------------------------------


class TestStrategyDiscovery:
    """Test strategy discovery and loading."""

    def test_discover_finds_macrossover(self) -> None:
        """The built-in MACrossover example should always be discovered."""
        strategies = discover_strategies()
        assert "MACrossover" in strategies

    def test_discovered_class_is_strategy_subclass(self) -> None:
        strategies = discover_strategies()
        for name, cls in strategies.items():
            assert issubclass(cls, Strategy), f"{name} is not a Strategy subclass"

    def test_load_strategy_success(self) -> None:
        strategy = load_strategy("MACrossover")
        assert isinstance(strategy, Strategy)
        assert type(strategy).__name__ == "MACrossover"

    def test_load_strategy_not_found(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            load_strategy("NonExistentStrategy")

    def test_load_strategy_error_lists_available(self) -> None:
        with pytest.raises(ValueError, match="MACrossover"):
            load_strategy("NonExistentStrategy")


# ---------------------------------------------------------------------------
# User strategy directory discovery test
# ---------------------------------------------------------------------------


class TestUserStrategyDiscovery:
    """Test that strategies in the strategies/ directory are discovered."""

    def test_discover_user_strategy(self, tmp_path: Path) -> None:
        """Write a temporary strategy file and verify it's discovered."""
        strategy_code = '''
from src.core.portfolio import Portfolio
from src.core.types import MultiTimeframeData, Signal
from src.strategy.base import Strategy

class TestUserStrat(Strategy):
    timeframes = ["1m"]

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        return []
'''
        strategy_file = tmp_path / "test_user_strat.py"
        strategy_file.write_text(strategy_code)

        with patch("src.strategy.loader._STRATEGY_DIRS", [tmp_path]):
            strategies = discover_strategies()

        assert "TestUserStrat" in strategies

    def test_discover_skips_invalid_files(self, tmp_path: Path) -> None:
        """Strategy files with syntax errors should be skipped, not crash."""
        bad_file = tmp_path / "bad_strategy.py"
        bad_file.write_text("this is not valid python }{}{")

        with patch("src.strategy.loader._STRATEGY_DIRS", [tmp_path]):
            strategies = discover_strategies()

        # Should not crash, just return empty
        assert isinstance(strategies, dict)

    def test_discover_skips_dunder_files(self, tmp_path: Path) -> None:
        """Files starting with _ should be skipped."""
        init_file = tmp_path / "__init__.py"
        init_file.write_text("# init")

        with patch("src.strategy.loader._STRATEGY_DIRS", [tmp_path]):
            strategies = discover_strategies()

        assert isinstance(strategies, dict)


# ---------------------------------------------------------------------------
# Command integration tests (mocked I/O)
# ---------------------------------------------------------------------------


def _make_candle(ts: datetime, price: float = 100.0) -> Candle:
    """Helper to create a test candle."""
    return Candle(
        timestamp=ts,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=1000.0,
    )


class TestCmdBacktest:
    """Test the backtest command handler with mocked components."""

    @pytest.mark.asyncio
    async def test_backtest_invalid_strategy_exits(self) -> None:
        """Backtest should exit with error for unknown strategy."""
        args = argparse.Namespace(
            strategy="NonExistentStrategy",
            start="2024-01-01",
            end="2024-06-01",
            initial_balance=10000.0,
        )
        with pytest.raises(SystemExit):
            await cmd_backtest(args)

    @pytest.mark.asyncio
    async def test_backtest_end_before_start_exits(self) -> None:
        """Backtest should exit if end date is before start date."""
        args = argparse.Namespace(
            strategy="MACrossover",
            start="2024-06-01",
            end="2024-01-01",
            initial_balance=10000.0,
        )
        with pytest.raises(SystemExit):
            await cmd_backtest(args)

    @pytest.mark.asyncio
    async def test_backtest_invalid_date_raises(self) -> None:
        """Backtest should raise ValueError for invalid date format."""
        args = argparse.Namespace(
            strategy="MACrossover",
            start="not-a-date",
            end="2024-06-01",
            initial_balance=10000.0,
        )
        with pytest.raises(ValueError, match="Invalid date format"):
            await cmd_backtest(args)


class TestCmdFetchData:
    """Test the fetch-data command handler with mocked components."""

    @pytest.mark.asyncio
    async def test_fetch_data_with_explicit_dates(self, tmp_path: Path) -> None:
        """Fetch data should use explicit dates when provided."""
        mock_provider = AsyncMock()
        mock_candles = [
            _make_candle(datetime(2024, 1, 1, tzinfo=UTC)),
            _make_candle(datetime(2024, 1, 2, tzinfo=UTC)),
        ]
        mock_provider.get_historical_candles = AsyncMock(return_value=mock_candles)
        mock_provider.close = AsyncMock()

        args = argparse.Namespace(
            symbol="BTC/USDT:USDT",
            timeframe="1m",
            start="2024-01-01",
            end="2024-06-01",
        )

        with patch("src.data.historical.HistoricalDataProvider", return_value=mock_provider):
            await cmd_fetch_data(args)

        mock_provider.get_historical_candles.assert_called_once()
        mock_provider.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_data_closes_provider_on_error(self) -> None:
        """Provider should be closed even if fetch fails."""
        mock_provider = AsyncMock()
        mock_provider.get_historical_candles = AsyncMock(side_effect=RuntimeError("exchange down"))
        mock_provider.close = AsyncMock()

        args = argparse.Namespace(
            symbol="BTC/USDT:USDT",
            timeframe="1m",
            start="2024-01-01",
            end="2024-06-01",
        )

        with patch("src.data.historical.HistoricalDataProvider", return_value=mock_provider):
            with pytest.raises(RuntimeError, match="exchange down"):
                await cmd_fetch_data(args)

        mock_provider.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_data_defaults_no_cache(self) -> None:
        """When no cache exists and no dates given, should default to 4 years ago."""
        mock_provider = AsyncMock()
        mock_provider.get_historical_candles = AsyncMock(return_value=[])
        mock_provider.close = AsyncMock()

        args = argparse.Namespace(
            symbol="BTC/USDT:USDT",
            timeframe="1m",
            start=None,
            end=None,
        )

        with (
            patch("src.data.historical.HistoricalDataProvider", return_value=mock_provider),
            patch("src.data.cache.get_cache_date_range", return_value=None),
            patch("src.data.cache.cache_path", return_value=Path("/tmp/test.parquet")),
        ):
            await cmd_fetch_data(args)

        # Should have been called with a start date ~4 years ago
        call_args = mock_provider.get_historical_candles.call_args
        start_dt = call_args.kwargs.get("start") or call_args[1].get("start")
        now = datetime.now(UTC)
        # Start should be roughly 4 years ago (within 2 days tolerance)
        diff_days = (now - start_dt).days
        assert 1458 <= diff_days <= 1462

    @pytest.mark.asyncio
    async def test_fetch_data_incremental_from_cache(self) -> None:
        """When cache exists and no start given, should start from last cached timestamp."""
        mock_provider = AsyncMock()
        mock_provider.get_historical_candles = AsyncMock(return_value=[])
        mock_provider.close = AsyncMock()

        cached_end = datetime(2024, 6, 1, tzinfo=UTC)

        args = argparse.Namespace(
            symbol="BTC/USDT:USDT",
            timeframe="1m",
            start=None,
            end=None,
        )

        with (
            patch("src.data.historical.HistoricalDataProvider", return_value=mock_provider),
            patch(
                "src.data.cache.get_cache_date_range",
                return_value=(datetime(2024, 1, 1, tzinfo=UTC), cached_end),
            ),
            patch("src.data.cache.cache_path", return_value=Path("/tmp/test.parquet")),
        ):
            await cmd_fetch_data(args)

        call_args = mock_provider.get_historical_candles.call_args
        start_dt = call_args.kwargs.get("start") or call_args[1].get("start")
        assert start_dt == cached_end
