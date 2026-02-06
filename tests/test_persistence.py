"""Tests for the persistence layer — async SQLite database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from src.core.portfolio import Portfolio
from src.core.types import Position, Trade
from src.persistence.database import Database

# --- Helpers ---


def _make_position(
    id: str = "pos_001",
    side: str = "long",
    entry_price: float = 100_000.0,
    entry_time: datetime | None = None,
    size: float = 0.05,
    size_usd: float = 5_000.0,
    stop_loss: float = 95_000.0,
    take_profit: float = 105_000.0,
) -> Position:
    """Create a Position with sensible defaults for testing."""
    if entry_time is None:
        entry_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    return Position(
        id=id,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        entry_time=entry_time,
        size=size,
        size_usd=size_usd,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def _make_trade(
    id: str = "trd_001",
    side: str = "long",
    entry_price: float = 100_000.0,
    exit_price: float = 105_000.0,
    entry_time: datetime | None = None,
    exit_time: datetime | None = None,
    size: float = 0.05,
    size_usd: float = 5_000.0,
    pnl: float = 250.0,
    pnl_percent: float = 5.0,
    exit_reason: str = "take_profit",
) -> Trade:
    """Create a Trade with sensible defaults for testing."""
    if entry_time is None:
        entry_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
    if exit_time is None:
        exit_time = datetime(2024, 6, 15, 14, 30, 0, tzinfo=UTC)
    return Trade(
        id=id,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        exit_price=exit_price,
        entry_time=entry_time,
        exit_time=exit_time,
        size=size,
        size_usd=size_usd,
        pnl=pnl,
        pnl_percent=pnl_percent,
        exit_reason=exit_reason,  # type: ignore[arg-type]
    )


# --- Fixtures ---


@pytest_asyncio.fixture
async def db() -> AsyncIterator[Database]:
    """Create an in-memory database for testing."""
    database = Database(":memory:")
    await database.initialize()
    yield database
    await database.close()


# --- Database unit tests ---


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db: Database) -> None:
        """Verify all four tables exist after initialize().

        The real test: all operations below should succeed on an initialized DB
        without raising any "table not found" errors.
        """
        positions = await db.get_open_positions()
        assert positions == []

        trades = await db.get_trades()
        assert trades == []

        portfolio = await db.get_portfolio()
        assert portfolio is None

        state = await db.get_strategy_state("unknown")
        assert state is None


class TestPositions:
    @pytest.mark.asyncio
    async def test_save_position_roundtrip(self, db: Database) -> None:
        """Save a Position, retrieve it, compare all fields."""
        pos = _make_position()
        await db.save_position(pos)

        positions = await db.get_open_positions()
        assert len(positions) == 1
        loaded = positions[0]

        assert loaded.id == pos.id
        assert loaded.side == pos.side
        assert loaded.entry_price == pytest.approx(pos.entry_price)
        assert loaded.entry_time == pos.entry_time
        assert loaded.size == pytest.approx(pos.size)
        assert loaded.size_usd == pytest.approx(pos.size_usd)
        assert loaded.stop_loss == pytest.approx(pos.stop_loss)
        assert loaded.take_profit == pytest.approx(pos.take_profit)

    @pytest.mark.asyncio
    async def test_delete_position(self, db: Database) -> None:
        """Save then delete a position, verify empty."""
        pos = _make_position()
        await db.save_position(pos)
        await db.delete_position(pos.id)

        positions = await db.get_open_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_open_positions_empty(self, db: Database) -> None:
        """Returns empty list on empty DB."""
        positions = await db.get_open_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_multiple_positions(self, db: Database) -> None:
        """Save 3 positions, verify all returned."""
        p1 = _make_position(id="pos_a", entry_price=100_000.0)
        p2 = _make_position(id="pos_b", side="short", entry_price=101_000.0)
        p3 = _make_position(id="pos_c", entry_price=99_000.0)

        await db.save_position(p1)
        await db.save_position(p2)
        await db.save_position(p3)

        positions = await db.get_open_positions()
        assert len(positions) == 3
        ids = {p.id for p in positions}
        assert ids == {"pos_a", "pos_b", "pos_c"}

    @pytest.mark.asyncio
    async def test_save_position_upsert(self, db: Database) -> None:
        """Saving a position with the same ID should update it (INSERT OR REPLACE)."""
        pos = _make_position(id="pos_upsert", stop_loss=90_000.0)
        await db.save_position(pos)

        updated = _make_position(id="pos_upsert", stop_loss=92_000.0)
        await db.save_position(updated)

        positions = await db.get_open_positions()
        assert len(positions) == 1
        assert positions[0].stop_loss == pytest.approx(92_000.0)


class TestTrades:
    @pytest.mark.asyncio
    async def test_save_trade_roundtrip(self, db: Database) -> None:
        """Save a Trade, retrieve it, compare all fields."""
        trade = _make_trade()
        await db.save_trade(trade)

        trades = await db.get_trades()
        assert len(trades) == 1
        loaded = trades[0]

        assert loaded.id == trade.id
        assert loaded.side == trade.side
        assert loaded.entry_price == pytest.approx(trade.entry_price)
        assert loaded.exit_price == pytest.approx(trade.exit_price)
        assert loaded.entry_time == trade.entry_time
        assert loaded.exit_time == trade.exit_time
        assert loaded.size == pytest.approx(trade.size)
        assert loaded.size_usd == pytest.approx(trade.size_usd)
        assert loaded.pnl == pytest.approx(trade.pnl)
        assert loaded.pnl_percent == pytest.approx(trade.pnl_percent)
        assert loaded.exit_reason == trade.exit_reason

    @pytest.mark.asyncio
    async def test_get_trades_empty(self, db: Database) -> None:
        """Returns empty list on empty DB."""
        trades = await db.get_trades()
        assert trades == []


class TestPortfolio:
    @pytest.mark.asyncio
    async def test_save_portfolio_roundtrip(self, db: Database) -> None:
        """Save a Portfolio, retrieve it, compare fields."""
        portfolio = Portfolio(initial_balance=10_000.0, balance=9_500.0)
        await db.save_portfolio(portfolio)

        loaded = await db.get_portfolio()
        assert loaded is not None
        assert loaded.initial_balance == pytest.approx(10_000.0)
        assert loaded.balance == pytest.approx(9_500.0)

    @pytest.mark.asyncio
    async def test_get_portfolio_none(self, db: Database) -> None:
        """Returns None on empty DB."""
        portfolio = await db.get_portfolio()
        assert portfolio is None

    @pytest.mark.asyncio
    async def test_save_portfolio_upsert(self, db: Database) -> None:
        """Saving portfolio twice updates the single row."""
        p1 = Portfolio(initial_balance=10_000.0, balance=10_000.0)
        await db.save_portfolio(p1)

        p2 = Portfolio(initial_balance=10_000.0, balance=9_000.0)
        await db.save_portfolio(p2)

        loaded = await db.get_portfolio()
        assert loaded is not None
        assert loaded.balance == pytest.approx(9_000.0)


class TestStrategyState:
    @pytest.mark.asyncio
    async def test_save_strategy_state_roundtrip(self, db: Database) -> None:
        """Save a dict with nested values, load it back, compare."""
        state = {
            "counter": 42,
            "flag": True,
            "nested": {"prices": [100.0, 101.5, 99.8], "label": "test"},
        }
        await db.save_strategy_state("MACrossover", state)

        loaded = await db.get_strategy_state("MACrossover")
        assert loaded is not None
        assert loaded == state

    @pytest.mark.asyncio
    async def test_get_strategy_state_none(self, db: Database) -> None:
        """Returns None for unknown strategy name."""
        state = await db.get_strategy_state("NonExistent")
        assert state is None

    @pytest.mark.asyncio
    async def test_save_strategy_state_upsert(self, db: Database) -> None:
        """Saving state for the same strategy name updates it."""
        await db.save_strategy_state("MyStrat", {"v": 1})
        await db.save_strategy_state("MyStrat", {"v": 2})

        loaded = await db.get_strategy_state("MyStrat")
        assert loaded is not None
        assert loaded["v"] == 2


class TestDatetimeUtc:
    @pytest.mark.asyncio
    async def test_datetime_utc_roundtrip_position(self, db: Database) -> None:
        """Verify timezone info is preserved after save/load for positions."""
        entry_time = datetime(2024, 3, 15, 8, 30, 45, tzinfo=UTC)
        pos = _make_position(entry_time=entry_time)
        await db.save_position(pos)

        positions = await db.get_open_positions()
        loaded = positions[0]
        assert loaded.entry_time.tzinfo is not None
        assert loaded.entry_time == entry_time

    @pytest.mark.asyncio
    async def test_datetime_utc_roundtrip_trade(self, db: Database) -> None:
        """Verify timezone info is preserved after save/load for trades."""
        entry_time = datetime(2024, 3, 15, 8, 30, 45, tzinfo=UTC)
        exit_time = datetime(2024, 3, 15, 10, 15, 30, tzinfo=UTC)
        trade = _make_trade(entry_time=entry_time, exit_time=exit_time)
        await db.save_trade(trade)

        trades = await db.get_trades()
        loaded = trades[0]
        assert loaded.entry_time.tzinfo is not None
        assert loaded.exit_time.tzinfo is not None
        assert loaded.entry_time == entry_time
        assert loaded.exit_time == exit_time


class TestClearAll:
    @pytest.mark.asyncio
    async def test_clear_all(self, db: Database) -> None:
        """Save data to all tables, clear, verify all empty."""
        await db.save_position(_make_position())
        await db.save_trade(_make_trade())
        await db.save_portfolio(Portfolio(initial_balance=10_000.0))
        await db.save_strategy_state("Strat", {"x": 1})

        await db.clear_all()

        assert await db.get_open_positions() == []
        assert await db.get_trades() == []
        assert await db.get_portfolio() is None
        assert await db.get_strategy_state("Strat") is None
