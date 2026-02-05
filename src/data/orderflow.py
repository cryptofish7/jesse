"""Orderflow data: Open Interest and Cumulative Volume Delta."""

from __future__ import annotations

import logging
import math

from src.core.types import Candle

logger = logging.getLogger(__name__)


def approximate_cvd(candles: list[Candle]) -> list[Candle]:
    """Compute approximate CVD from candle data.

    For each candle: delta = volume * sign(close - open).
    CVD is the cumulative sum of deltas.

    Returns new Candle objects with the cvd field populated.
    """
    result: list[Candle] = []
    cumulative = 0.0

    for c in candles:
        if c.cvd != 0.0:
            # Already has CVD data, keep it
            cumulative = c.cvd
            result.append(c)
            continue

        diff = c.close - c.open
        if diff > 0:
            sign = 1.0
        elif diff < 0:
            sign = -1.0
        else:
            sign = 0.0

        cumulative += c.volume * sign
        result.append(Candle(
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
            open_interest=c.open_interest,
            cvd=cumulative,
        ))

    return result


def enrich_with_oi(
    candles: list[Candle],
    oi_data: dict[int, float],
) -> list[Candle]:
    """Merge Open Interest data into candles.

    Args:
        candles: Existing candles.
        oi_data: Mapping of unix timestamp (ms) to OI value.

    Returns new Candle objects with open_interest populated.
    """
    result: list[Candle] = []
    for c in candles:
        ts_ms = int(c.timestamp.timestamp() * 1000)
        oi = oi_data.get(ts_ms, c.open_interest)
        if oi != c.open_interest:
            result.append(Candle(
                timestamp=c.timestamp,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                open_interest=oi,
                cvd=c.cvd,
            ))
        else:
            result.append(c)
    return result
