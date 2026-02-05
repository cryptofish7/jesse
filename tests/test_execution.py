"""Tests for BacktestExecutor — open, close, PnL, and edge cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.core.portfolio import Portfolio
from src.core.types import Position, Signal, Trade
from src.execution.backtest import BacktestExecutor, _build_trade

# --- Helpers ---


def _portfolio(balance: float = 10_000.0, price: float = 100.0) -> Portfolio:
    p = Portfolio(initial_balance=balance)
    p.update_price(price)
    return p


def _position(
    id_: str = "pos-001",
    side: str = "long",
    entry_price: float = 100.0,
    size: float = 1.0,
    size_usd: float = 100.0,
    stop_loss: float = 90.0,
    take_profit: float = 110.0,
) -> Position:
    return Position(
        id=id_,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        entry_time=datetime(2024, 1, 1, tzinfo=UTC),
        size=size,
        size_usd=size_usd,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


# --- TestBacktestExecutorOpen ---


class TestBacktestExecutorOpen:
    """Tests for opening positions via execute()."""

    def setup_method(self) -> None:
        self.executor = BacktestExecutor(initial_balance=10_000.0)
        self.executor.current_time = datetime(2024, 6, 1, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_open_long(self) -> None:
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, 100.0, portfolio)

        assert isinstance(result, Position)
        assert result.side == "long"
        assert result.entry_price == 100.0
        assert result.size_usd == pytest.approx(1_000.0)  # 10% of 10k equity
        assert result.size == pytest.approx(10.0)  # 1000 / 100
        assert result.stop_loss == 90.0
        assert result.take_profit == 110.0
        assert result.entry_time == datetime(2024, 6, 1, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_open_short(self) -> None:
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        signal = Signal.open_short(size_percent=0.05, stop_loss=110.0, take_profit=90.0)
        result = await self.executor.execute(signal, 100.0, portfolio)

        assert isinstance(result, Position)
        assert result.side == "short"
        assert result.size_usd == pytest.approx(500.0)  # 5% of 10k
        assert result.size == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_size_calculation(self) -> None:
        """size_usd = equity * size_percent, size = size_usd / price."""
        portfolio = _portfolio(balance=5_000.0, price=50_000.0)
        signal = Signal.open_long(size_percent=0.2, stop_loss=45_000.0, take_profit=55_000.0)
        result = await self.executor.execute(signal, 50_000.0, portfolio)

        assert isinstance(result, Position)
        assert result.size_usd == pytest.approx(1_000.0)  # 20% of 5k
        assert result.size == pytest.approx(0.02)  # 1000 / 50000

    @pytest.mark.asyncio
    async def test_unique_ids(self) -> None:
        portfolio = _portfolio()
        signal = Signal.open_long(size_percent=0.01, stop_loss=90.0, take_profit=110.0)

        r1 = await self.executor.execute(signal, 100.0, portfolio)
        r2 = await self.executor.execute(signal, 100.0, portfolio)

        assert isinstance(r1, Position)
        assert isinstance(r2, Position)
        assert r1.id != r2.id

    @pytest.mark.asyncio
    async def test_reject_missing_size(self) -> None:
        portfolio = _portfolio()
        signal = Signal(direction="long", stop_loss=90.0, take_profit=110.0)  # no size
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_missing_sl(self) -> None:
        portfolio = _portfolio()
        signal = Signal(direction="long", size_percent=0.1, take_profit=110.0)  # no SL
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_missing_tp(self) -> None:
        portfolio = _portfolio()
        signal = Signal(direction="long", size_percent=0.1, stop_loss=90.0)  # no TP
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_zero_equity(self) -> None:
        portfolio = _portfolio(balance=0.0, price=100.0)
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_insufficient_balance(self) -> None:
        """If size_usd > balance, reject the signal."""
        portfolio = _portfolio(balance=100.0, price=100.0)
        signal = Signal.open_long(size_percent=1.0, stop_loss=90.0, take_profit=110.0)
        # size_usd = equity(100) * 1.0 = 100, balance = 100 — edge case: exactly equal is OK
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert isinstance(result, Position)

        # Now with truly insufficient balance: equity > balance scenario
        portfolio_low = Portfolio(initial_balance=100.0)
        portfolio_low.balance = 50.0  # Spent 50 on a prior position
        portfolio_low.update_price(100.0)
        # equity = balance(50) + unrealized(0) = 50
        signal_big = Signal.open_long(size_percent=1.5, stop_loss=90.0, take_profit=110.0)
        # size_usd = 50 * 1.5 = 75 > balance(50) — rejected
        result_rejected = await self.executor.execute(signal_big, 100.0, portfolio_low)
        assert result_rejected is None


# --- TestBacktestExecutorClose ---


class TestBacktestExecutorClose:
    """Tests for closing positions via execute() with close signals."""

    def setup_method(self) -> None:
        self.executor = BacktestExecutor()
        self.executor.current_time = datetime(2024, 6, 2, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_close_specific_position(self) -> None:
        portfolio = _portfolio()
        pos = _position(id_="abc123")
        portfolio.open_position(pos)

        signal = Signal.close(position_id="abc123")
        result = await self.executor.execute(signal, 105.0, portfolio)

        assert isinstance(result, Trade)
        assert result.id == "abc123"
        assert result.exit_price == 105.0
        assert result.exit_reason == "signal"

    @pytest.mark.asyncio
    async def test_close_first_position_when_no_id(self) -> None:
        portfolio = _portfolio()
        pos1 = _position(id_="first")
        pos2 = _position(id_="second")
        portfolio.open_position(pos1)
        portfolio.open_position(pos2)

        signal = Signal.close()  # No position_id
        result = await self.executor.execute(signal, 105.0, portfolio)

        assert isinstance(result, Trade)
        assert result.id == "first"

    @pytest.mark.asyncio
    async def test_close_nonexistent_position(self) -> None:
        portfolio = _portfolio()
        pos = _position(id_="real")
        portfolio.open_position(pos)

        signal = Signal.close(position_id="fake")
        result = await self.executor.execute(signal, 105.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_close_empty_portfolio(self) -> None:
        portfolio = _portfolio()
        signal = Signal.close()
        result = await self.executor.execute(signal, 105.0, portfolio)
        assert result is None


# --- TestBacktestExecutorClosePosition ---


class TestBacktestExecutorClosePosition:
    """Tests for close_position() method (used by engine for SL/TP)."""

    def setup_method(self) -> None:
        self.executor = BacktestExecutor()
        self.executor.current_time = datetime(2024, 6, 2, 12, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_close_with_stop_loss(self) -> None:
        pos = _position(side="long", entry_price=100.0)
        trade = await self.executor.close_position(pos, 90.0, "stop_loss")

        assert isinstance(trade, Trade)
        assert trade.exit_price == 90.0
        assert trade.exit_reason == "stop_loss"
        assert trade.exit_time == datetime(2024, 6, 2, 12, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_close_with_take_profit(self) -> None:
        pos = _position(side="long", entry_price=100.0)
        trade = await self.executor.close_position(pos, 110.0, "take_profit")

        assert trade.exit_price == 110.0
        assert trade.exit_reason == "take_profit"

    @pytest.mark.asyncio
    async def test_close_with_signal(self) -> None:
        pos = _position(side="short", entry_price=100.0)
        trade = await self.executor.close_position(pos, 95.0, "signal")

        assert trade.exit_reason == "signal"


# --- TestPnLCalculation ---


class TestPnLCalculation:
    """Tests for PnL calculation in _build_trade."""

    def test_long_profit(self) -> None:
        pos = _position(side="long", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 110.0, datetime(2024, 1, 2, tzinfo=UTC), "take_profit")

        assert trade.pnl == pytest.approx(20.0)  # (110 - 100) * 2
        assert trade.pnl_percent == pytest.approx(10.0)  # 20/200 * 100

    def test_long_loss(self) -> None:
        pos = _position(side="long", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 90.0, datetime(2024, 1, 2, tzinfo=UTC), "stop_loss")

        assert trade.pnl == pytest.approx(-20.0)  # (90 - 100) * 2
        assert trade.pnl_percent == pytest.approx(-10.0)

    def test_short_profit(self) -> None:
        pos = _position(side="short", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 90.0, datetime(2024, 1, 2, tzinfo=UTC), "take_profit")

        assert trade.pnl == pytest.approx(20.0)  # (100 - 90) * 2
        assert trade.pnl_percent == pytest.approx(10.0)

    def test_short_loss(self) -> None:
        pos = _position(side="short", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 110.0, datetime(2024, 1, 2, tzinfo=UTC), "stop_loss")

        assert trade.pnl == pytest.approx(-20.0)  # (100 - 110) * 2
        assert trade.pnl_percent == pytest.approx(-10.0)

    def test_breakeven(self) -> None:
        pos = _position(side="long", entry_price=100.0, size=5.0, size_usd=500.0)
        trade = _build_trade(pos, 100.0, datetime(2024, 1, 2, tzinfo=UTC), "signal")

        assert trade.pnl == pytest.approx(0.0)
        assert trade.pnl_percent == pytest.approx(0.0)

    def test_fractional_size(self) -> None:
        """BTC-like: small position size, large price."""
        pos = _position(side="long", entry_price=50_000.0, size=0.01, size_usd=500.0)
        trade = _build_trade(pos, 55_000.0, datetime(2024, 1, 2, tzinfo=UTC), "take_profit")

        assert trade.pnl == pytest.approx(50.0)  # (55000 - 50000) * 0.01
        assert trade.pnl_percent == pytest.approx(10.0)  # 50/500 * 100

    def test_trade_preserves_position_fields(self) -> None:
        """Trade should carry over the position's entry data."""
        pos = _position(id_="xyz", side="long", entry_price=100.0, size=1.0, size_usd=100.0)
        exit_time = datetime(2024, 7, 1, tzinfo=UTC)
        trade = _build_trade(pos, 110.0, exit_time, "take_profit")

        assert trade.id == "xyz"
        assert trade.side == "long"
        assert trade.entry_price == 100.0
        assert trade.entry_time == pos.entry_time
        assert trade.exit_time == exit_time
        assert trade.size == 1.0
        assert trade.size_usd == 100.0


# --- TestEdgeCases ---


class TestEdgeCases:
    """Edge case tests for executor."""

    def setup_method(self) -> None:
        self.executor = BacktestExecutor()
        self.executor.current_time = datetime(2024, 6, 1, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_close_signal_empty_portfolio_returns_none(self) -> None:
        """Close signal with no open positions returns None."""
        portfolio = _portfolio()
        signal = Signal(direction="close")
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_zero_price(self) -> None:
        """Opening at price=0 is rejected to avoid ZeroDivisionError."""
        portfolio = _portfolio()
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, 0.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_negative_price(self) -> None:
        """Opening at negative price is rejected."""
        portfolio = _portfolio()
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, -50.0, portfolio)
        assert result is None
