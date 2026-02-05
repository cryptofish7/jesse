"""Tests for Portfolio class."""

from datetime import datetime

from src.core.portfolio import Portfolio
from src.core.types import Position, Trade


def _make_position(**overrides) -> Position:
    defaults = dict(
        id="p1",
        side="long",
        entry_price=100.0,
        entry_time=datetime(2024, 1, 1),
        size=0.1,
        size_usd=10.0,
        stop_loss=90.0,
        take_profit=120.0,
    )
    defaults.update(overrides)
    return Position(**defaults)


def _make_trade(**overrides) -> Trade:
    defaults = dict(
        id="t1",
        side="long",
        entry_price=100.0,
        exit_price=110.0,
        entry_time=datetime(2024, 1, 1),
        exit_time=datetime(2024, 1, 2),
        size=0.1,
        size_usd=10.0,
        pnl=1.0,
        pnl_percent=10.0,
        exit_reason="take_profit",
    )
    defaults.update(overrides)
    return Trade(**defaults)


class TestPortfolio:
    def test_initial_state(self):
        p = Portfolio(initial_balance=10000.0)
        assert p.balance == 10000.0
        assert p.equity == 10000.0
        assert p.has_position is False
        assert p.positions == []
        assert p.trades == []

    def test_equity_at_no_positions(self):
        p = Portfolio(initial_balance=10000.0)
        assert p.equity_at(50000.0) == 10000.0

    def test_equity_at_with_position(self):
        p = Portfolio(initial_balance=10000.0)
        pos = _make_position(entry_price=100.0, size=1.0, size_usd=100.0)
        p.open_position(pos)
        # balance = 10000 - 100 = 9900
        # unrealized pnl at 110 = (110 - 100) * 1.0 = 10
        assert p.equity_at(110.0) == 9910.0

    def test_open_position(self):
        p = Portfolio(initial_balance=10000.0)
        pos = _make_position(size_usd=500.0)
        p.open_position(pos)
        assert p.balance == 9500.0
        assert p.has_position is True
        assert len(p.positions) == 1

    def test_close_position(self):
        p = Portfolio(initial_balance=10000.0)
        pos = _make_position(id="p1", size_usd=500.0)
        p.open_position(pos)
        assert p.balance == 9500.0

        trade = _make_trade(id="p1", size_usd=500.0, pnl=50.0)
        p.close_position("p1", trade)

        assert p.balance == 10050.0  # 9500 + 500 + 50
        assert p.has_position is False
        assert len(p.trades) == 1
        assert p.trades[0].pnl == 50.0

    def test_get_position_found(self):
        p = Portfolio(initial_balance=10000.0)
        pos = _make_position(id="abc")
        p.open_position(pos)
        assert p.get_position("abc") is pos

    def test_get_position_not_found(self):
        p = Portfolio(initial_balance=10000.0)
        assert p.get_position("nonexistent") is None

    def test_multiple_positions(self):
        p = Portfolio(initial_balance=10000.0)
        p.open_position(_make_position(id="p1", size_usd=1000.0))
        p.open_position(_make_position(id="p2", size_usd=2000.0))
        assert p.balance == 7000.0
        assert len(p.positions) == 2

        # Close one
        trade = _make_trade(id="p1", size_usd=1000.0, pnl=100.0)
        p.close_position("p1", trade)
        assert p.balance == 8100.0  # 7000 + 1000 + 100
        assert len(p.positions) == 1
        assert p.positions[0].id == "p2"

    def test_close_position_with_loss(self):
        p = Portfolio(initial_balance=10000.0)
        pos = _make_position(id="p1", size_usd=500.0)
        p.open_position(pos)

        trade = _make_trade(id="p1", size_usd=500.0, pnl=-50.0)
        p.close_position("p1", trade)
        assert p.balance == 9950.0  # 9500 + 500 + (-50)

    def test_explicit_balance(self):
        p = Portfolio(initial_balance=10000.0, balance=5000.0)
        assert p.balance == 5000.0
