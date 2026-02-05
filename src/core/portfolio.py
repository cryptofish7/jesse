"""Portfolio management — tracks positions, balance, and equity."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.types import Position, Trade


@dataclass
class Portfolio:
    """Tracks open positions, closed trades, and account balance."""

    initial_balance: float
    balance: float | None = None
    positions: list[Position] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    _current_price: float = 0.0

    def __post_init__(self) -> None:
        if self.balance is None:
            self.balance = self.initial_balance

    def update_price(self, price: float) -> None:
        """Update the last known market price for equity calculation."""
        self._current_price = price

    @property
    def equity(self) -> float:
        """Balance plus unrealized PnL of all open positions."""
        unrealized = sum(p.unrealized_pnl(self._current_price) for p in self.positions)
        return self.balance + unrealized  # type: ignore[operator]

    @property
    def has_position(self) -> bool:
        return len(self.positions) > 0

    def get_position(self, position_id: str) -> Position | None:
        return next((p for p in self.positions if p.id == position_id), None)

    def open_position(self, position: Position) -> None:
        """Add a position and lock its margin from balance."""
        self.positions.append(position)
        self.balance -= position.size_usd  # type: ignore[operator]

    def close_position(self, position_id: str, trade: Trade) -> None:
        """Remove a position and credit the realized PnL to balance."""
        original_count = len(self.positions)
        self.positions = [p for p in self.positions if p.id != position_id]
        if len(self.positions) == original_count:
            raise ValueError(f"Position '{position_id}' not found")
        self.trades.append(trade)
        self.balance += trade.size_usd + trade.pnl  # type: ignore[operator]
