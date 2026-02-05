"""Executor ABC — defines the interface for trade execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from src.core.portfolio import Portfolio
from src.core.types import Position, Signal, Trade


class Executor(ABC):
    """Base class for trade executors (backtest, paper, etc.)."""

    @abstractmethod
    async def execute(
        self,
        signal: Signal,
        current_price: float,
        portfolio: Portfolio,
    ) -> Position | Trade | None:
        """Execute a signal.

        Returns new Position for opens, Trade for closes, None if rejected.
        """

    @abstractmethod
    async def close_position(
        self,
        position: Position,
        price: float,
        reason: Literal["stop_loss", "take_profit", "signal"],
    ) -> Trade:
        """Close a position at the given price."""
