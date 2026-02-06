"""Tests for engine + persistence integration.

Verifies:
1. Force-closed positions at end of backtest are persisted (trade saved, position deleted).
2. DB connection is closed after backtest completes (normal and exception paths).
3. Restored positions don't duplicate existing portfolio positions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.core.engine import Engine
from src.core.types import Candle, Position, Signal
from src.data.provider import DataProvider
from src.execution.backtest import BacktestExecutor
from src.strategy.base import Strategy

# --- Test helpers ---


class _AlwaysLongStrategy(Strategy):
    """Open a long on first candle, then do nothing."""

    timeframes = ["1m"]

    def __init__(self) -> None:
        self._opened = False

    def on_candle(self, data, portfolio):  # type: ignore[override]
        if not self._opened and not portfolio.positions:
            self._opened = True
            return [Signal.open_long(size_percent=0.5, stop_loss=90_000.0, take_profit=110_000.0)]
        return []


class _NoOpStrategy(Strategy):
    """Never trades."""

    timeframes = ["1m"]

    def on_candle(self, data, portfolio):  # type: ignore[override]
        return []


def _make_candles(n: int, start_price: float = 100_000.0) -> list[Candle]:
    """Create *n* sequential 1m candles starting at *start_price*.

    Prices rise by 10 per candle (well within SL=90k / TP=110k range)
    so no SL/TP is triggered during the test window.
    """
    base = datetime(2024, 6, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for i in range(n):
        ts = base + timedelta(minutes=i)
        p = start_price + i * 10
        candles.append(
            Candle(
                timestamp=ts,
                open=p,
                high=p + 5,
                low=p - 5,
                close=p,
                volume=100.0,
            )
        )
    return candles


def _make_mock_db() -> AsyncMock:
    """Create a mock Database with all required async methods stubbed."""
    mock_db = AsyncMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.get_portfolio = AsyncMock(return_value=None)
    mock_db.get_open_positions = AsyncMock(return_value=[])
    mock_db.get_strategy_state = AsyncMock(return_value=None)
    mock_db.save_portfolio = AsyncMock()
    mock_db.save_strategy_state = AsyncMock()
    mock_db.save_position = AsyncMock()
    mock_db.delete_position = AsyncMock()
    mock_db.save_trade = AsyncMock()
    return mock_db


def _make_mock_provider(candles: list[Candle]) -> AsyncMock:
    """Create a mock DataProvider that returns the given candles."""
    mock_provider = AsyncMock(spec=DataProvider)
    mock_provider.symbol = "BTC/USDT:USDT"
    mock_provider.get_historical_candles = AsyncMock(return_value=candles)
    return mock_provider


# --- Tests ---


class TestCloseAllPositionsPersistence:
    """Verify force-closed positions at end of backtest are persisted."""

    @pytest.mark.asyncio
    async def test_force_close_persists_to_db(self) -> None:
        """When a position is still open at the end of the backtest,
        _close_all_positions must call delete_position and save_trade."""
        mock_db = _make_mock_db()
        # 200 candles: 100 warm-up + 100 backtest
        candles = _make_candles(200)

        engine = Engine(
            strategy=_AlwaysLongStrategy(),
            data_provider=_make_mock_provider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        # Replace the real DB with our mock
        engine._db = mock_db

        results = await engine.run_backtest()

        # The strategy opens 1 position. It doesn't hit SL/TP in our price range,
        # so it should be force-closed at end of backtest.
        assert results.total_trades >= 1

        # Verify: delete_position called for the force-closed position
        assert mock_db.delete_position.call_count >= 1, (
            "_close_all_positions must call db.delete_position"
        )
        # Verify: save_trade called for the force-closed position
        assert mock_db.save_trade.call_count >= 1, "_close_all_positions must call db.save_trade"

    @pytest.mark.asyncio
    async def test_force_close_trade_matches_position(self) -> None:
        """The trade saved to DB should have the same id as the position
        that was force-closed."""
        mock_db = _make_mock_db()
        candles = _make_candles(200)

        engine = Engine(
            strategy=_AlwaysLongStrategy(),
            data_provider=_make_mock_provider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        engine._db = mock_db

        await engine.run_backtest()

        # Collect all position IDs that were deleted and all trade IDs saved
        deleted_ids = {call.args[0] for call in mock_db.delete_position.call_args_list}
        saved_trade_ids = {call.args[0].id for call in mock_db.save_trade.call_args_list}
        # Every deleted position should have a corresponding trade saved
        assert deleted_ids <= saved_trade_ids


class TestDbConnectionClosed:
    """Verify DB connection is properly closed after backtest."""

    @pytest.mark.asyncio
    async def test_db_closed_after_successful_backtest(self) -> None:
        """DB.close() must be called after a normal backtest run."""
        mock_db = _make_mock_db()
        candles = _make_candles(200)

        engine = Engine(
            strategy=_NoOpStrategy(),
            data_provider=_make_mock_provider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        engine._db = mock_db

        await engine.run_backtest()

        mock_db.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_db_closed_on_exception(self) -> None:
        """DB.close() must be called even if an exception occurs during backtest."""
        mock_db = _make_mock_db()

        failing_provider = AsyncMock(spec=DataProvider)
        failing_provider.symbol = "BTC/USDT:USDT"
        failing_provider.get_historical_candles = AsyncMock(
            side_effect=RuntimeError("boom"),
        )

        engine = Engine(
            strategy=_NoOpStrategy(),
            data_provider=failing_provider,
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        engine._db = mock_db

        with pytest.raises(RuntimeError, match="boom"):
            await engine.run_backtest()

        mock_db.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_db_closed_on_empty_candles(self) -> None:
        """DB.close() must be called even when no candles are returned."""
        mock_db = _make_mock_db()

        engine = Engine(
            strategy=_NoOpStrategy(),
            data_provider=_make_mock_provider([]),  # no candles
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        engine._db = mock_db

        await engine.run_backtest()

        mock_db.close.assert_awaited_once()


class TestRestoreStateNoDuplicates:
    """Verify _restore_state doesn't create duplicate positions."""

    @pytest.mark.asyncio
    async def test_restore_clears_existing_positions(self) -> None:
        """If portfolio already has positions before _restore_state is called,
        they must be replaced by the DB positions (not appended)."""
        mock_db = _make_mock_db()
        db_position = Position(
            id="db_pos_1",
            side="long",
            entry_price=100_000.0,
            entry_time=datetime(2024, 6, 1, tzinfo=UTC),
            size=0.05,
            size_usd=5_000.0,
            stop_loss=95_000.0,
            take_profit=105_000.0,
        )
        mock_db.get_open_positions = AsyncMock(return_value=[db_position])

        candles = _make_candles(200)

        engine = Engine(
            strategy=_NoOpStrategy(),
            data_provider=_make_mock_provider(candles),
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        engine._db = mock_db

        # Manually add a stale position to simulate pre-existing state
        stale_position = Position(
            id="stale_1",
            side="long",
            entry_price=99_000.0,
            entry_time=datetime(2024, 5, 30, tzinfo=UTC),
            size=0.01,
            size_usd=1_000.0,
            stop_loss=90_000.0,
            take_profit=110_000.0,
        )
        engine.portfolio.positions.append(stale_position)

        # Call _restore_state directly to test the clear logic
        await engine._restore_state()

        # After restore, portfolio should have only the DB position, not the stale one
        assert len(engine.portfolio.positions) == 1
        assert engine.portfolio.positions[0].id == "db_pos_1"

    @pytest.mark.asyncio
    async def test_restore_empty_db_clears_positions(self) -> None:
        """If DB has no positions, restore should clear any existing ones."""
        mock_db = _make_mock_db()
        mock_db.get_open_positions = AsyncMock(return_value=[])

        engine = Engine(
            strategy=_NoOpStrategy(),
            data_provider=_make_mock_provider([]),
            executor=BacktestExecutor(initial_balance=10_000.0),
            persist=True,
            start=datetime(2024, 6, 1, tzinfo=UTC),
            end=datetime(2024, 6, 2, tzinfo=UTC),
        )
        engine._db = mock_db

        # Pre-populate with a stale position
        engine.portfolio.positions.append(
            Position(
                id="stale_2",
                side="short",
                entry_price=101_000.0,
                entry_time=datetime(2024, 5, 28, tzinfo=UTC),
                size=0.02,
                size_usd=2_000.0,
                stop_loss=110_000.0,
                take_profit=90_000.0,
            )
        )

        await engine._restore_state()

        assert len(engine.portfolio.positions) == 0
