"""Live data provider — streams real-time candle data via WebSocket.

Connects to Binance Futures kline WebSocket streams, parses incoming messages
into Candle objects, and invokes a callback on each candle close. Supports
multiple timeframes, auto-reconnect with exponential backoff, and approximate
CVD/OI enrichment.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import websockets
import websockets.exceptions
from websockets.asyncio.client import ClientConnection

from src.config import settings
from src.core.types import Candle
from src.data.provider import DataProvider

logger = logging.getLogger(__name__)

# Binance Futures WebSocket base URL
BINANCE_FUTURES_WS = "wss://fstream.binance.com/ws"

# Reconnect settings
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0
BACKOFF_MULTIPLIER = 2.0
MAX_CONSECUTIVE_FAILURES = 10

# Binance kline timeframe mapping (Jesse TF -> Binance interval)
_TF_TO_BINANCE: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}


def _symbol_to_binance(symbol: str) -> str:
    """Convert ccxt-style symbol to Binance WebSocket stream symbol.

    Example: 'BTC/USDT:USDT' -> 'btcusdt'
    """
    # Remove the settlement part (e.g., ':USDT')
    base = symbol.split(":")[0]
    # Remove the slash and lowercase
    return base.replace("/", "").lower()


def _build_stream_names(symbol: str, timeframes: list[str]) -> list[str]:
    """Build Binance combined stream names for kline subscriptions.

    Example: ['btcusdt@kline_1m', 'btcusdt@kline_4h']
    """
    binance_symbol = _symbol_to_binance(symbol)
    streams: list[str] = []
    for tf in timeframes:
        binance_tf = _TF_TO_BINANCE.get(tf)
        if binance_tf is None:
            raise ValueError(f"Unsupported timeframe for Binance WebSocket: {tf}")
        streams.append(f"{binance_symbol}@kline_{binance_tf}")
    return streams


def _build_ws_url(streams: list[str]) -> str:
    """Build the Binance combined stream WebSocket URL.

    Uses the combined stream endpoint to subscribe to multiple streams
    over a single connection.
    """
    stream_path = "/".join(streams)
    return f"{BINANCE_FUTURES_WS}/{stream_path}"


def _parse_kline_message(data: dict) -> tuple[str, Candle, bool] | None:
    """Parse a Binance kline WebSocket message into a (timeframe, Candle, is_closed) tuple.

    Returns None if the message is not a kline event.
    """
    event_type = data.get("e")
    if event_type != "kline":
        return None

    kline = data.get("k")
    if kline is None:
        return None

    # Extract timeframe
    interval = kline.get("i", "")
    # Reverse lookup: find Jesse timeframe from Binance interval
    tf = None
    for jesse_tf, binance_tf in _TF_TO_BINANCE.items():
        if binance_tf == interval:
            tf = jesse_tf
            break
    if tf is None:
        return None

    # Parse candle data
    timestamp_ms = kline.get("t", 0)
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)

    open_price = float(kline.get("o", 0))
    high = float(kline.get("h", 0))
    low = float(kline.get("l", 0))
    close = float(kline.get("c", 0))
    volume = float(kline.get("v", 0))
    is_closed = bool(kline.get("x", False))

    # Approximate CVD: volume * sign(close - open)
    diff = close - open_price
    if diff > 0:
        sign = 1.0
    elif diff < 0:
        sign = -1.0
    else:
        sign = 0.0
    cvd = volume * sign

    candle = Candle(
        timestamp=timestamp,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        cvd=cvd,
    )

    return tf, candle, is_closed


class LiveDataProvider(DataProvider):
    """Streams real-time candle data from Binance Futures via WebSocket.

    Implements the DataProvider ABC. The subscribe() method connects to
    Binance kline streams, parses messages, and calls the callback with
    completed candles. Auto-reconnects with exponential backoff on connection
    failures.

    Usage:
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")

        async def on_candle(timeframe: str, candle: Candle) -> None:
            print(f"{timeframe}: {candle}")

        await provider.subscribe("BTC/USDT:USDT", ["1m", "4h"], on_candle)
        # Runs until unsubscribe() is called
    """

    def __init__(self, symbol: str | None = None) -> None:
        self.symbol = symbol or settings.symbol
        self._ws: ClientConnection | None = None
        self._running = False
        self._listen_task: asyncio.Task[None] | None = None
        self._consecutive_failures = 0
        self._cvd_accumulator: dict[str, float] = {}

    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Delegate historical data fetching to HistoricalDataProvider.

        The live provider doesn't store historical data itself — it defers
        to the historical provider for any warm-up needs.
        """
        from src.data.historical import HistoricalDataProvider

        historical = HistoricalDataProvider(symbol=symbol)
        try:
            return await historical.get_historical_candles(symbol, timeframe, start, end)
        finally:
            await historical.close()

    async def subscribe(
        self,
        symbol: str,
        timeframes: list[str],
        callback: Callable[[str, Candle], Awaitable[None]],
    ) -> None:
        """Subscribe to live candle updates via Binance WebSocket.

        Connects to the Binance Futures combined kline stream for all
        requested timeframes. The callback is invoked with (timeframe, candle)
        only when a candle closes (kline.x == true).

        This method runs indefinitely until unsubscribe() is called.
        It auto-reconnects on connection failures with exponential backoff.

        Args:
            symbol: Trading pair (e.g., 'BTC/USDT:USDT').
            timeframes: List of timeframe strings (e.g., ['1m', '4h']).
            callback: Async function called with (timeframe, candle) on close.
        """
        self._running = True
        self._consecutive_failures = 0
        # Initialize CVD accumulators for each timeframe
        for tf in timeframes:
            self._cvd_accumulator[tf] = 0.0

        streams = _build_stream_names(symbol, timeframes)
        ws_url = _build_ws_url(streams)

        logger.info(
            "Subscribing to live kline streams: %s (symbol=%s, timeframes=%s)",
            ws_url,
            symbol,
            timeframes,
        )

        backoff = INITIAL_BACKOFF_S

        while self._running:
            try:
                async with websockets.connect(ws_url) as ws:
                    self._ws = ws
                    self._consecutive_failures = 0
                    backoff = INITIAL_BACKOFF_S
                    logger.info("WebSocket connected to %s", ws_url)

                    await self._listen(ws, callback)

                # _listen returned normally — either _running was set False
                # (graceful shutdown) or the stream ended unexpectedly.
                if not self._running:
                    break
                # Stream ended without error — reconnect after brief pause
                logger.info("WebSocket stream ended, reconnecting...")

            except websockets.exceptions.ConnectionClosed as e:
                if not self._running:
                    break
                self._consecutive_failures += 1
                logger.warning(
                    "WebSocket connection closed (code=%s, reason=%s). "
                    "Reconnecting in %.1fs (attempt %d/%d)...",
                    e.code if hasattr(e, "code") else "?",
                    e.reason if hasattr(e, "reason") else "?",
                    backoff,
                    self._consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                )

            except (OSError, websockets.exceptions.WebSocketException) as e:
                if not self._running:
                    break
                self._consecutive_failures += 1
                logger.warning(
                    "WebSocket error: %s. Reconnecting in %.1fs (attempt %d/%d)...",
                    e,
                    backoff,
                    self._consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                )

            except asyncio.CancelledError:
                break

            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error(
                    "Max consecutive failures (%d) reached. Stopping live data provider.",
                    MAX_CONSECUTIVE_FAILURES,
                )
                self._running = False
                break

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_S)

        self._ws = None
        logger.info("Live data provider stopped.")

    async def _listen(
        self,
        ws: ClientConnection,
        callback: Callable[[str, Candle], Awaitable[None]],
    ) -> None:
        """Listen for kline messages and dispatch closed candles to the callback."""
        async for raw_message in ws:
            if not self._running:
                break

            try:
                data = json.loads(raw_message)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON WebSocket message, skipping")
                continue

            # Combined stream wraps data in {"stream": "...", "data": {...}}
            # Single stream sends data directly
            if "data" in data:
                data = data["data"]

            result = _parse_kline_message(data)
            if result is None:
                continue

            tf, candle, is_closed = result

            if is_closed:
                # Accumulate CVD for this timeframe
                prev_cvd = self._cvd_accumulator.get(tf, 0.0)
                cumulative_cvd = prev_cvd + candle.cvd
                self._cvd_accumulator[tf] = cumulative_cvd

                # Create candle with cumulative CVD
                enriched_candle = Candle(
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    open_interest=candle.open_interest,
                    cvd=cumulative_cvd,
                )

                logger.debug(
                    "Candle closed: %s %s O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f CVD=%.2f",
                    tf,
                    enriched_candle.timestamp,
                    enriched_candle.open,
                    enriched_candle.high,
                    enriched_candle.low,
                    enriched_candle.close,
                    enriched_candle.volume,
                    enriched_candle.cvd,
                )

                try:
                    await callback(tf, enriched_candle)
                except Exception:
                    logger.exception("Error in candle callback for %s", tf)

    async def unsubscribe(self) -> None:
        """Close the WebSocket connection and stop listening.

        Safe to call even if not currently subscribed.
        """
        self._running = False

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("Error closing WebSocket (ignored)", exc_info=True)
            self._ws = None

        if self._listen_task is not None and not self._listen_task.done():
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None

        self._cvd_accumulator.clear()
        logger.info("Unsubscribed from live data.")

    @property
    def is_connected(self) -> bool:
        """Return True if the WebSocket is currently connected."""
        return self._ws is not None and self._running
