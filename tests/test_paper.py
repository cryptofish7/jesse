"""Tests for PaperExecutor — paper trading execution, real-time PnL, and SL/TP monitoring."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from src.core.portfolio import Portfolio
from src.core.types import Position, Signal, Trade
from src.execution.paper import PaperExecutor, _build_trade

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


# --- TestPaperExecutorOpen ---


class TestPaperExecutorOpen:
    """Tests for opening positions via execute()."""

    def setup_method(self) -> None:
        self.executor = PaperExecutor(initial_balance=10_000.0)

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
        # Paper executor uses real time (UTC-aware)
        assert result.entry_time.tzinfo is not None

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
    async def test_fills_at_market_price(self) -> None:
        """Paper executor fills at the given current_price (market price)."""
        portfolio = _portfolio(balance=10_000.0, price=50_000.0)
        signal = Signal.open_long(size_percent=0.1, stop_loss=45_000.0, take_profit=55_000.0)
        result = await self.executor.execute(signal, 50_000.0, portfolio)

        assert isinstance(result, Position)
        assert result.entry_price == 50_000.0
        assert result.size_usd == pytest.approx(1_000.0)
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
        signal = Signal(direction="long", stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_missing_sl(self) -> None:
        portfolio = _portfolio()
        signal = Signal(direction="long", size_percent=0.1, take_profit=110.0)
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_missing_tp(self) -> None:
        portfolio = _portfolio()
        signal = Signal(direction="long", size_percent=0.1, stop_loss=90.0)
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
        portfolio_low = Portfolio(initial_balance=100.0)
        portfolio_low.balance = 50.0
        portfolio_low.update_price(100.0)
        signal = Signal.open_long(size_percent=1.5, stop_loss=90.0, take_profit=110.0)
        # equity = 50, size_usd = 50 * 1.5 = 75 > balance(50) — rejected
        result = await self.executor.execute(signal, 100.0, portfolio_low)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_zero_price(self) -> None:
        portfolio = _portfolio()
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, 0.0, portfolio)
        assert result is None

    @pytest.mark.asyncio
    async def test_reject_negative_price(self) -> None:
        portfolio = _portfolio()
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, -50.0, portfolio)
        assert result is None


# --- TestPaperExecutorClose ---


class TestPaperExecutorClose:
    """Tests for closing positions via execute() with close signals."""

    def setup_method(self) -> None:
        self.executor = PaperExecutor()

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
        # UTC-aware exit time
        assert result.exit_time.tzinfo is not None

    @pytest.mark.asyncio
    async def test_close_first_position_when_no_id(self) -> None:
        portfolio = _portfolio()
        pos1 = _position(id_="first")
        pos2 = _position(id_="second")
        portfolio.open_position(pos1)
        portfolio.open_position(pos2)

        signal = Signal.close()
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


# --- TestPaperExecutorClosePosition ---


class TestPaperExecutorClosePosition:
    """Tests for close_position() method (used by engine for SL/TP)."""

    def setup_method(self) -> None:
        self.executor = PaperExecutor()

    @pytest.mark.asyncio
    async def test_close_with_stop_loss(self) -> None:
        pos = _position(side="long", entry_price=100.0)
        trade = await self.executor.close_position(pos, 90.0, "stop_loss")

        assert isinstance(trade, Trade)
        assert trade.exit_price == 90.0
        assert trade.exit_reason == "stop_loss"
        assert trade.exit_time.tzinfo is not None  # UTC-aware

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


class TestPaperPnLCalculation:
    """Tests for PnL calculation in paper executor's _build_trade."""

    def test_long_profit(self) -> None:
        pos = _position(side="long", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 110.0, datetime(2024, 1, 2, tzinfo=UTC), "take_profit")

        assert trade.pnl == pytest.approx(20.0)  # (110 - 100) * 2
        assert trade.pnl_percent == pytest.approx(10.0)  # 20/200 * 100

    def test_long_loss(self) -> None:
        pos = _position(side="long", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 90.0, datetime(2024, 1, 2, tzinfo=UTC), "stop_loss")

        assert trade.pnl == pytest.approx(-20.0)
        assert trade.pnl_percent == pytest.approx(-10.0)

    def test_short_profit(self) -> None:
        pos = _position(side="short", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 90.0, datetime(2024, 1, 2, tzinfo=UTC), "take_profit")

        assert trade.pnl == pytest.approx(20.0)
        assert trade.pnl_percent == pytest.approx(10.0)

    def test_short_loss(self) -> None:
        pos = _position(side="short", entry_price=100.0, size=2.0, size_usd=200.0)
        trade = _build_trade(pos, 110.0, datetime(2024, 1, 2, tzinfo=UTC), "stop_loss")

        assert trade.pnl == pytest.approx(-20.0)
        assert trade.pnl_percent == pytest.approx(-10.0)

    def test_breakeven(self) -> None:
        pos = _position(side="long", entry_price=100.0, size=5.0, size_usd=500.0)
        trade = _build_trade(pos, 100.0, datetime(2024, 1, 2, tzinfo=UTC), "signal")

        assert trade.pnl == pytest.approx(0.0)
        assert trade.pnl_percent == pytest.approx(0.0)


# --- TestRealTimePnL ---


class TestRealTimePnL:
    """Tests for real-time PnL updates via check_price_update."""

    def setup_method(self) -> None:
        self.executor = PaperExecutor()

    def test_unrealized_pnl_updates_on_price_change(self) -> None:
        """Portfolio equity reflects unrealized PnL after price update."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=80.0,
            take_profit=120.0,
        )
        portfolio.open_position(pos)
        # balance = 10000 - 100 = 9900, equity = 9900 + unrealized(0) = 9900

        # Price goes up
        trades = self.executor.check_price_update(105.0, portfolio)
        assert len(trades) == 0
        # unrealized PnL = (105 - 100) * 1.0 = 5.0
        assert portfolio.equity == pytest.approx(9905.0)

        # Price goes down
        trades = self.executor.check_price_update(98.0, portfolio)
        assert len(trades) == 0
        # unrealized PnL = (98 - 100) * 1.0 = -2.0
        assert portfolio.equity == pytest.approx(9898.0)

    def test_unrealized_pnl_short_position(self) -> None:
        """Short position unrealized PnL is correct after price update."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="short",
            entry_price=100.0,
            size=2.0,
            size_usd=200.0,
            stop_loss=120.0,
            take_profit=80.0,
        )
        portfolio.open_position(pos)
        # balance = 10000 - 200 = 9800

        trades = self.executor.check_price_update(95.0, portfolio)
        assert len(trades) == 0
        # unrealized PnL = (100 - 95) * 2.0 = 10.0
        assert portfolio.equity == pytest.approx(9810.0)

    def test_multiple_positions_pnl(self) -> None:
        """Multiple positions' unrealized PnL aggregated correctly."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos1 = _position(
            id_="long-1",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=80.0,
            take_profit=120.0,
        )
        pos2 = _position(
            id_="short-1",
            side="short",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=120.0,
            take_profit=80.0,
        )
        portfolio.open_position(pos1)
        portfolio.open_position(pos2)
        # balance = 10000 - 100 - 100 = 9800

        trades = self.executor.check_price_update(105.0, portfolio)
        assert len(trades) == 0
        # long PnL = (105-100)*1 = 5, short PnL = (100-105)*1 = -5
        # Total unrealized = 0
        assert portfolio.equity == pytest.approx(9800.0)


# --- TestSLTPTickMonitoring ---


class TestSLTPTickMonitoring:
    """Tests for SL/TP monitoring on individual ticks via check_price_update."""

    def setup_method(self) -> None:
        self.executor = PaperExecutor()

    def test_long_stop_loss_triggered(self) -> None:
        """Long position SL triggers when price drops to or below SL."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            id_="long-sl",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(94.0, portfolio)

        assert len(trades) == 1
        assert trades[0].exit_reason == "stop_loss"
        assert trades[0].exit_price == 95.0  # Exits at SL price, not tick price
        assert trades[0].id == "long-sl"
        # Position should be removed from portfolio
        assert len(portfolio.positions) == 0

    def test_long_take_profit_triggered(self) -> None:
        """Long position TP triggers when price rises to or above TP."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            id_="long-tp",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=90.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(112.0, portfolio)

        assert len(trades) == 1
        assert trades[0].exit_reason == "take_profit"
        assert trades[0].exit_price == 110.0  # Exits at TP price
        assert trades[0].id == "long-tp"
        assert len(portfolio.positions) == 0

    def test_short_stop_loss_triggered(self) -> None:
        """Short position SL triggers when price rises to or above SL."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            id_="short-sl",
            side="short",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=105.0,
            take_profit=90.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(106.0, portfolio)

        assert len(trades) == 1
        assert trades[0].exit_reason == "stop_loss"
        assert trades[0].exit_price == 105.0
        assert len(portfolio.positions) == 0

    def test_short_take_profit_triggered(self) -> None:
        """Short position TP triggers when price drops to or below TP."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            id_="short-tp",
            side="short",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=110.0,
            take_profit=90.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(89.0, portfolio)

        assert len(trades) == 1
        assert trades[0].exit_reason == "take_profit"
        assert trades[0].exit_price == 90.0
        assert len(portfolio.positions) == 0

    def test_no_trigger_within_range(self) -> None:
        """No SL/TP triggered when price stays between SL and TP."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=90.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(105.0, portfolio)
        assert len(trades) == 0
        assert len(portfolio.positions) == 1

    def test_exact_sl_price_triggers(self) -> None:
        """SL triggers when price equals exactly the SL level."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(95.0, portfolio)
        assert len(trades) == 1
        assert trades[0].exit_reason == "stop_loss"

    def test_exact_tp_price_triggers(self) -> None:
        """TP triggers when price equals exactly the TP level."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=90.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(110.0, portfolio)
        assert len(trades) == 1
        assert trades[0].exit_reason == "take_profit"

    def test_multiple_positions_one_triggered(self) -> None:
        """Only the position whose SL/TP is hit gets closed."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos_tight = _position(
            id_="tight",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=98.0,
            take_profit=102.0,
        )
        pos_wide = _position(
            id_="wide",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=80.0,
            take_profit=120.0,
        )
        portfolio.open_position(pos_tight)
        portfolio.open_position(pos_wide)

        trades = self.executor.check_price_update(97.0, portfolio)

        assert len(trades) == 1
        assert trades[0].id == "tight"
        assert trades[0].exit_reason == "stop_loss"
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].id == "wide"

    def test_multiple_positions_all_triggered(self) -> None:
        """All positions whose SL/TP is hit get closed in one update."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos1 = _position(
            id_="pos1",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        pos2 = _position(
            id_="pos2",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=96.0,
            take_profit=115.0,
        )
        portfolio.open_position(pos1)
        portfolio.open_position(pos2)

        # Price drops below both SL levels
        trades = self.executor.check_price_update(90.0, portfolio)

        assert len(trades) == 2
        assert {t.id for t in trades} == {"pos1", "pos2"}
        assert all(t.exit_reason == "stop_loss" for t in trades)
        assert len(portfolio.positions) == 0

    def test_pnl_correct_on_sl_close(self) -> None:
        """PnL is calculated correctly when SL closes a position."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=2.0,
            size_usd=200.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(94.0, portfolio)

        assert len(trades) == 1
        # PnL = (95 - 100) * 2 = -10.0
        assert trades[0].pnl == pytest.approx(-10.0)
        assert trades[0].pnl_percent == pytest.approx(-5.0)  # -10/200 * 100

    def test_pnl_correct_on_tp_close(self) -> None:
        """PnL is calculated correctly when TP closes a position."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=2.0,
            size_usd=200.0,
            stop_loss=90.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(112.0, portfolio)

        assert len(trades) == 1
        # PnL = (110 - 100) * 2 = 20.0
        assert trades[0].pnl == pytest.approx(20.0)
        assert trades[0].pnl_percent == pytest.approx(10.0)


# --- TestPositionChangeCallback ---


class TestPositionChangeCallback:
    """Tests for the on_position_change callback (alerting)."""

    def setup_method(self) -> None:
        self.callback = MagicMock()
        self.executor = PaperExecutor(on_position_change=self.callback)

    @pytest.mark.asyncio
    async def test_callback_on_open(self) -> None:
        portfolio = _portfolio()
        signal = Signal.open_long(size_percent=0.1, stop_loss=90.0, take_profit=110.0)
        result = await self.executor.execute(signal, 100.0, portfolio)

        assert isinstance(result, Position)
        self.callback.assert_called_once()
        event, obj = self.callback.call_args[0]
        assert event == "opened"
        assert isinstance(obj, Position)

    @pytest.mark.asyncio
    async def test_callback_on_close_signal(self) -> None:
        portfolio = _portfolio()
        pos = _position(id_="cb-close")
        portfolio.open_position(pos)

        signal = Signal.close(position_id="cb-close")
        result = await self.executor.execute(signal, 105.0, portfolio)

        assert isinstance(result, Trade)
        self.callback.assert_called_once()
        event, obj = self.callback.call_args[0]
        assert event == "closed_signal"
        assert isinstance(obj, Trade)

    @pytest.mark.asyncio
    async def test_callback_on_close_position_sl(self) -> None:
        pos = _position(side="long", entry_price=100.0)
        await self.executor.close_position(pos, 90.0, "stop_loss")

        self.callback.assert_called_once()
        event, obj = self.callback.call_args[0]
        assert event == "closed_stop_loss"
        assert isinstance(obj, Trade)

    @pytest.mark.asyncio
    async def test_callback_on_close_position_tp(self) -> None:
        pos = _position(side="long", entry_price=100.0)
        await self.executor.close_position(pos, 110.0, "take_profit")

        self.callback.assert_called_once()
        event, obj = self.callback.call_args[0]
        assert event == "closed_take_profit"
        assert isinstance(obj, Trade)

    def test_callback_on_tick_sl_trigger(self) -> None:
        """Callback fires when tick-level SL/TP monitoring triggers a close."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            id_="tick-sl",
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(94.0, portfolio)

        assert len(trades) == 1
        self.callback.assert_called_once()
        event, obj = self.callback.call_args[0]
        assert event == "closed_stop_loss"
        assert isinstance(obj, Trade)

    @pytest.mark.asyncio
    async def test_no_callback_on_rejection(self) -> None:
        """Callback is NOT called when a signal is rejected."""
        portfolio = _portfolio()
        signal = Signal(direction="long", stop_loss=90.0, take_profit=110.0)  # no size
        result = await self.executor.execute(signal, 100.0, portfolio)

        assert result is None
        self.callback.assert_not_called()

    def test_no_callback_when_no_trigger(self) -> None:
        """Callback is NOT called when price stays within SL/TP range."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=90.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(105.0, portfolio)

        assert len(trades) == 0
        self.callback.assert_not_called()


# --- TestEdgeCases ---


class TestPaperEdgeCases:
    """Edge case tests for paper executor."""

    def setup_method(self) -> None:
        self.executor = PaperExecutor()

    def test_check_price_update_empty_portfolio(self) -> None:
        """No crash when checking price on empty portfolio."""
        portfolio = _portfolio()
        trades = self.executor.check_price_update(100.0, portfolio)
        assert trades == []

    def test_check_price_update_updates_portfolio_price(self) -> None:
        """check_price_update always updates the portfolio's current price."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        self.executor.check_price_update(42_000.0, portfolio)
        assert portfolio._current_price == 42_000.0

    @pytest.mark.asyncio
    async def test_close_signal_empty_portfolio_returns_none(self) -> None:
        portfolio = _portfolio()
        signal = Signal(direction="close")
        result = await self.executor.execute(signal, 100.0, portfolio)
        assert result is None

    def test_initial_balance_attribute(self) -> None:
        """PaperExecutor exposes initial_balance for Engine to read."""
        executor = PaperExecutor(initial_balance=25_000.0)
        assert executor.initial_balance == 25_000.0

    def test_exit_time_is_utc_aware(self) -> None:
        """All trades from check_price_update have UTC-aware exit times."""
        portfolio = _portfolio(balance=10_000.0, price=100.0)
        pos = _position(
            side="long",
            entry_price=100.0,
            size=1.0,
            size_usd=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        )
        portfolio.open_position(pos)

        trades = self.executor.check_price_update(94.0, portfolio)
        assert len(trades) == 1
        assert trades[0].exit_time.tzinfo is not None
