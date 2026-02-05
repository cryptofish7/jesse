"""Core data structures used throughout the Jesse trading system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Candle:
    """OHLCV candle with optional orderflow data."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float = 0.0
    cvd: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass(frozen=True, slots=True)
class Signal:
    """Trading signal emitted by a strategy."""

    direction: Literal["long", "short", "close"]
    size_percent: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    position_id: str | None = None

    @classmethod
    def open_long(
        cls,
        size_percent: float,
        stop_loss: float,
        take_profit: float,
    ) -> Signal:
        return cls("long", size_percent, stop_loss, take_profit)

    @classmethod
    def open_short(
        cls,
        size_percent: float,
        stop_loss: float,
        take_profit: float,
    ) -> Signal:
        return cls("short", size_percent, stop_loss, take_profit)

    @classmethod
    def close(cls, position_id: str | None = None) -> Signal:
        return cls("close", position_id=position_id)


@dataclass(slots=True)
class Position:
    """An open position tracked by the portfolio."""

    id: str
    side: Literal["long", "short"]
    entry_price: float
    entry_time: datetime
    size: float  # In base currency (BTC)
    size_usd: float
    stop_loss: float
    take_profit: float

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL given the current market price."""
        if self.side == "long":
            return (current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - current_price) * self.size

    @staticmethod
    def generate_id() -> str:
        return uuid4().hex[:12]


@dataclass(frozen=True, slots=True)
class Trade:
    """A closed position (completed trade)."""

    id: str
    side: Literal["long", "short"]
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    size: float
    size_usd: float
    pnl: float
    pnl_percent: float
    exit_reason: Literal["stop_loss", "take_profit", "signal"]


@dataclass(slots=True)
class TimeframeData:
    """Candle data for a single timeframe."""

    latest: Candle
    history: list[Candle] = field(default_factory=list)


class MultiTimeframeData(dict[str, TimeframeData]):
    """Dict-like access to multiple timeframes: data['1m'], data['4h'], etc."""
