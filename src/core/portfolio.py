"""Portfolio management — tracks positions, balance, and equity."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.types import Position, Trade


@dataclass
class Portfolio:
    """Tracks open positions, closed trades, and account balance."""

    initial_balance: float
    balance: float = 0.0
    positions: list[Position] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.balance == 0.0:
            self.balance = self.initial_balance

    @property
    def equity(self) -> float:
        """Balance plus unrealized PnL of all open positions.

        Note: requires a current price to be meaningful. When no positions
        are open, equity equals balance.  For positions, we use entry_price
        as a conservative fallback (unrealized PnL = 0).
        """
        return self.balance

    def equity_at(self, current_price: float) -> float:
        """Balance plus unrealized PnL at a given market price."""
        unrealized = sum(p.unrealized_pnl(current_price) for p in self.positions)
        return self.balance + unrealized

    @property
    def has_position(self) -> bool:
        return len(self.positions) > 0

    def get_position(self, position_id: str) -> Position | None:
        return next((p for p in self.positions if p.id == position_id), None)

    def open_position(self, position: Position) -> None:
        """Add a position and lock its margin from balance."""
        self.positions.append(position)
        self.balance -= position.size_usd

    def close_position(self, position_id: str, trade: Trade) -> None:
        """Remove a position and credit the realized PnL to balance."""
        self.positions = [p for p in self.positions if p.id != position_id]
        self.trades.append(trade)
        self.balance += trade.size_usd + trade.pnl
