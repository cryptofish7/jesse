"""Historical data provider — fetches from exchange, caches to Parquet."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import ccxt.async_support as ccxt

from src.config import settings
from src.core.types import Candle
from src.data import cache, orderflow
from src.data.provider import DataProvider

logger = logging.getLogger(__name__)

# ccxt timeframe strings
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d", "1w")

# Max candles per request (exchange-specific, conservative default)
MAX_CANDLES_PER_REQUEST = 1000


def _create_exchange() -> ccxt.Exchange:
    """Create an async ccxt exchange instance."""
    exchange_map = {
        "bybit": ccxt.bybit,
        "binance": ccxt.binance,
        "hyperliquid": ccxt.hyperliquid,
    }
    cls = exchange_map.get(settings.exchange)
    if cls is None:
        raise ValueError(f"Unsupported exchange: {settings.exchange}")
    return cls({"enableRateLimit": True})


def _filter_range(candles: list[Candle], start_ms: int, end_ms: int) -> list[Candle]:
    """Filter candles to those within the given timestamp range (inclusive)."""
    return [c for c in candles if start_ms <= int(c.timestamp.timestamp() * 1000) <= end_ms]


def _timeframe_ms(tf: str) -> int:
    """Convert timeframe string to milliseconds."""
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    num = int(tf[:-1])
    unit = tf[-1]
    return num * units[unit]


class HistoricalDataProvider(DataProvider):
    """Fetches historical candle data from an exchange, caching to Parquet."""

    def __init__(self, symbol: str | None = None) -> None:
        self.symbol = symbol or settings.symbol
        self._exchange: ccxt.Exchange | None = None

    async def _get_exchange(self) -> ccxt.Exchange:
        if self._exchange is None:
            self._exchange = _create_exchange()
        return self._exchange

    async def close(self) -> None:
        if self._exchange is not None:
            await self._exchange.close()
            self._exchange = None

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Fetch historical candles, using cache where possible."""
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        # Check cache
        cached = cache.read_candles(symbol, timeframe)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        if cached:
            cache_start_ms = int(cached[0].timestamp.timestamp() * 1000)
            cache_end_ms = int(cached[-1].timestamp.timestamp() * 1000)

            # Determine what ranges are missing
            fetch_ranges: list[tuple[int, int]] = []
            if start_ms < cache_start_ms:
                fetch_ranges.append((start_ms, cache_start_ms))
            if end_ms > cache_end_ms:
                fetch_ranges.append((cache_end_ms, end_ms))

            if not fetch_ranges:
                # Cache covers the full range
                return _filter_range(cached, start_ms, end_ms)

            # Fetch missing ranges
            new_candles: list[Candle] = []
            for range_start, range_end in fetch_ranges:
                fetched = await self._fetch_from_exchange(symbol, timeframe, range_start, range_end)
                new_candles.extend(fetched)

            # Merge and save
            all_candles = cache.merge_candles(cached, new_candles)
            all_candles = orderflow.approximate_cvd(all_candles)
            cache.write_candles(symbol, timeframe, all_candles)

            return _filter_range(all_candles, start_ms, end_ms)

        # No cache — fetch everything
        fetched = await self._fetch_from_exchange(symbol, timeframe, start_ms, end_ms)
        fetched = orderflow.approximate_cvd(fetched)
        cache.write_candles(symbol, timeframe, fetched)
        return fetched

    async def _fetch_from_exchange(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int,
        end_ms: int,
    ) -> list[Candle]:
        """Fetch candles from the exchange with pagination and rate limiting."""
        exchange = await self._get_exchange()
        all_candles: list[Candle] = []
        since = start_ms
        tf_ms = _timeframe_ms(timeframe)

        logger.info(
            "Fetching %s %s candles from %s to %s",
            symbol,
            timeframe,
            datetime.fromtimestamp(start_ms / 1000, tz=UTC),
            datetime.fromtimestamp(end_ms / 1000, tz=UTC),
        )

        while since < end_ms:
            try:
                ohlcv = await exchange.fetch_ohlcv(
                    symbol,
                    timeframe,
                    since=since,
                    limit=MAX_CANDLES_PER_REQUEST,
                )
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limited, waiting 5s...")
                await asyncio.sleep(5)
                continue
            except ccxt.NetworkError as e:
                logger.warning("Network error: %s, retrying in 3s...", e)
                await asyncio.sleep(3)
                continue

            if not ohlcv:
                break

            for row in ohlcv:
                ts = datetime.fromtimestamp(row[0] / 1000, tz=UTC)
                if int(ts.timestamp() * 1000) > end_ms:
                    break
                all_candles.append(
                    Candle(
                        timestamp=ts,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                    )
                )

            last_ts = ohlcv[-1][0]
            since = last_ts + tf_ms

            up_to = datetime.fromtimestamp(last_ts / 1000, tz=UTC)
            logger.debug("Fetched %d candles, up to %s", len(ohlcv), up_to)

        logger.info("Total fetched: %d candles", len(all_candles))
        return all_candles

    async def subscribe(
        self,
        symbol: str,
        timeframes: list[str],
        callback: Callable[[str, Candle], Awaitable[None]],
    ) -> None:
        """Not supported for historical provider."""
        raise NotImplementedError("HistoricalDataProvider does not support live subscriptions")

    async def unsubscribe(self) -> None:
        """Clean up exchange connection."""
        await self.close()
