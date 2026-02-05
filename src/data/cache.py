"""Parquet cache for historical candle data."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.core.types import Candle
from src.config import settings

logger = logging.getLogger(__name__)

SCHEMA = pa.schema([
    ("timestamp", pa.timestamp("us")),
    ("open", pa.float64()),
    ("high", pa.float64()),
    ("low", pa.float64()),
    ("close", pa.float64()),
    ("volume", pa.float64()),
    ("open_interest", pa.float64()),
    ("cvd", pa.float64()),
])


def cache_path(symbol: str, timeframe: str) -> Path:
    """Generate the cache file path for a symbol/timeframe pair."""
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    return Path(settings.cache_path) / f"{safe_symbol}_{timeframe}.parquet"


def cache_exists(symbol: str, timeframe: str) -> bool:
    """Check if a cache file exists for the given symbol/timeframe."""
    return cache_path(symbol, timeframe).exists()


def read_candles(symbol: str, timeframe: str) -> list[Candle]:
    """Read cached candles from a Parquet file."""
    path = cache_path(symbol, timeframe)
    if not path.exists():
        return []

    table = pq.read_table(path)
    candles = []
    for i in range(table.num_rows):
        ts = table.column("timestamp")[i].as_py()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        candles.append(Candle(
            timestamp=ts,
            open=table.column("open")[i].as_py(),
            high=table.column("high")[i].as_py(),
            low=table.column("low")[i].as_py(),
            close=table.column("close")[i].as_py(),
            volume=table.column("volume")[i].as_py(),
            open_interest=table.column("open_interest")[i].as_py(),
            cvd=table.column("cvd")[i].as_py(),
        ))
    logger.debug("Read %d candles from %s", len(candles), path)
    return candles


def write_candles(symbol: str, timeframe: str, candles: list[Candle]) -> None:
    """Write candles to a Parquet file, overwriting any existing data."""
    if not candles:
        return

    path = cache_path(symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)

    arrays = {
        "timestamp": pa.array([c.timestamp for c in candles], type=pa.timestamp("us")),
        "open": pa.array([c.open for c in candles], type=pa.float64()),
        "high": pa.array([c.high for c in candles], type=pa.float64()),
        "low": pa.array([c.low for c in candles], type=pa.float64()),
        "close": pa.array([c.close for c in candles], type=pa.float64()),
        "volume": pa.array([c.volume for c in candles], type=pa.float64()),
        "open_interest": pa.array([c.open_interest for c in candles], type=pa.float64()),
        "cvd": pa.array([c.cvd for c in candles], type=pa.float64()),
    }
    table = pa.table(arrays, schema=SCHEMA)
    pq.write_table(table, path)
    logger.debug("Wrote %d candles to %s", len(candles), path)


def get_cache_date_range(symbol: str, timeframe: str) -> tuple[datetime, datetime] | None:
    """Return (earliest, latest) timestamps in the cache, or None if empty."""
    candles = read_candles(symbol, timeframe)
    if not candles:
        return None
    return candles[0].timestamp, candles[-1].timestamp


def merge_candles(existing: list[Candle], new: list[Candle]) -> list[Candle]:
    """Merge two sorted candle lists, deduplicating by timestamp."""
    by_ts: dict[datetime, Candle] = {}
    for c in existing:
        by_ts[c.timestamp] = c
    for c in new:
        by_ts[c.timestamp] = c
    return sorted(by_ts.values(), key=lambda c: c.timestamp)
