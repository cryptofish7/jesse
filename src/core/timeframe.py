"""Timeframe utilities and multi-timeframe aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.core.types import Candle, MultiTimeframeData, TimeframeData

# Ordered from lowest to highest resolution
TIMEFRAME_ORDER = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")

_TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
}


def get_timeframe_minutes(tf: str) -> int:
    """Return the number of minutes in a timeframe."""
    if tf not in _TF_MINUTES:
        raise ValueError(f"Unknown timeframe: {tf}")
    return _TF_MINUTES[tf]


def get_lower_timeframe(tf: str) -> str | None:
    """Return the next lower timeframe, or None if already at 1m."""
    if tf not in TIMEFRAME_ORDER:
        raise ValueError(f"Unknown timeframe: {tf}")
    idx = TIMEFRAME_ORDER.index(tf)
    if idx == 0:
        return None
    return TIMEFRAME_ORDER[idx - 1]


def is_timeframe_complete(tf: str, timestamp: datetime) -> bool:
    """Check if a candle close timestamp marks the completion of a higher TF candle.

    A higher timeframe candle completes when the 1m candle's close timestamp
    is aligned to the higher timeframe boundary. For example, a 5m candle
    completes at minute 0, 5, 10, etc.
    """
    minutes = get_timeframe_minutes(tf)
    if tf == "1w":
        # Weekly: completes when Sunday 23:59 UTC closes (Monday 00:00 boundary)
        return _is_week_boundary(timestamp)
    if tf == "1d":
        # Daily: completes at 00:00 UTC
        return timestamp.hour == 23 and timestamp.minute == 59
    # For sub-daily: check if (minute_of_day + 1) is divisible by TF minutes
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    return (minute_of_day + 1) % minutes == 0


def _is_week_boundary(timestamp: datetime) -> bool:
    """Check if the next minute after this timestamp is Monday 00:00 UTC."""
    # isoweekday: Monday=1, Sunday=7
    return timestamp.isoweekday() == 7 and timestamp.hour == 23 and timestamp.minute == 59


@dataclass
class _AggregatingCandle:
    """Tracks an in-progress higher-timeframe candle being built from 1m candles."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float = 0.0
    cvd: float = 0.0

    def update(self, candle: Candle) -> None:
        """Incorporate a new 1m candle into this aggregating candle."""
        self.high = max(self.high, candle.high)
        self.low = min(self.low, candle.low)
        self.close = candle.close
        self.volume += candle.volume
        self.open_interest = candle.open_interest
        self.cvd = candle.cvd

    def to_candle(self) -> Candle:
        """Finalize into a completed Candle."""
        return Candle(
            timestamp=self.open_time,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            open_interest=self.open_interest,
            cvd=self.cvd,
        )

    def to_in_progress_candle(self) -> Candle:
        """Return current state as a Candle (not yet complete)."""
        return self.to_candle()


@dataclass
class TimeframeAggregator:
    """Aggregates 1m candles into multiple higher timeframes.

    Usage:
        agg = TimeframeAggregator(timeframes=["1m", "4h"])
        agg.warm_up(historical_1m_candles)

        for candle_1m in new_candles:
            mtf_data = agg.update(candle_1m)
            # mtf_data has latest + history for each declared timeframe
    """

    timeframes: list[str]
    max_history: int = 525_600  # ~1 year of 1m candles per timeframe

    # Internal state — per-timeframe history of completed candles
    _history: dict[str, list[Candle]] = field(default_factory=dict, init=False)
    # In-progress candles for higher timeframes
    _building: dict[str, _AggregatingCandle | None] = field(
        default_factory=dict,
        init=False,
    )

    def __post_init__(self) -> None:
        for tf in self.timeframes:
            if tf not in _TF_MINUTES:
                raise ValueError(f"Unknown timeframe: {tf}")
            self._history[tf] = []
            if tf != "1m":
                self._building[tf] = None

    def warm_up(self, candles_1m: list[Candle]) -> None:
        """Pre-populate history from a batch of historical 1m candles.

        Processes all candles to build up higher-timeframe histories.
        """
        for candle in candles_1m:
            self._process_candle(candle)

    def update(self, candle_1m: Candle) -> MultiTimeframeData:
        """Process a new 1m candle and return the current multi-timeframe state.

        This is the main entry point called on each 1m candle close.
        """
        self._process_candle(candle_1m)
        return self._build_mtf_data(candle_1m)

    def _process_candle(self, candle_1m: Candle) -> None:
        """Update all timeframe histories with a new 1m candle."""
        # Always append 1m candle to 1m history
        if "1m" in self.timeframes:
            self._append_history("1m", candle_1m)

        # Update higher timeframes
        for tf in self.timeframes:
            if tf == "1m":
                continue

            building = self._building.get(tf)
            if building is None:
                # Start a new aggregating candle
                self._building[tf] = _AggregatingCandle(
                    open_time=candle_1m.timestamp,
                    open=candle_1m.open,
                    high=candle_1m.high,
                    low=candle_1m.low,
                    close=candle_1m.close,
                    volume=candle_1m.volume,
                    open_interest=candle_1m.open_interest,
                    cvd=candle_1m.cvd,
                )
            else:
                building.update(candle_1m)

            # Check if this timeframe completed
            if is_timeframe_complete(tf, candle_1m.timestamp):
                completed = self._building[tf]
                if completed is not None:
                    self._append_history(tf, completed.to_candle())
                    self._building[tf] = None

    def _append_history(self, tf: str, candle: Candle) -> None:
        """Append a candle to history, trimming to max_history."""
        history = self._history[tf]
        history.append(candle)
        if len(history) > self.max_history:
            # Trim oldest
            self._history[tf] = history[-self.max_history :]

    def _build_mtf_data(self, latest_1m: Candle) -> MultiTimeframeData:
        """Build MultiTimeframeData from current state."""
        mtf = MultiTimeframeData()

        for tf in self.timeframes:
            history = self._history[tf]

            if tf == "1m":
                latest = latest_1m
            else:
                # For higher timeframes, use the in-progress candle as "latest"
                building = self._building.get(tf)
                if building is not None:
                    latest = building.to_in_progress_candle()
                elif history:
                    latest = history[-1]
                else:
                    # No data yet — use the 1m candle as a placeholder
                    latest = latest_1m

            mtf[tf] = TimeframeData(latest=latest, history=list(history))

        return mtf

    def get_history(self, tf: str) -> list[Candle]:
        """Get the completed candle history for a timeframe."""
        return list(self._history.get(tf, []))
