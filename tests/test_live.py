"""Tests for the live data provider: WebSocket connection, candle parsing, reconnection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.core.types import Candle
from src.data.live import (
    BINANCE_FUTURES_WS,
    MAX_CONSECUTIVE_FAILURES,
    LiveDataProvider,
    _build_stream_names,
    _build_ws_url,
    _parse_kline_message,
    _symbol_to_binance,
)

# --- Helper to create a mock async-iterable WebSocket ---


def _make_mock_ws(messages: list[str]) -> AsyncMock:
    """Create a mock WebSocket that yields the given messages in order.

    After all messages are consumed, raises StopAsyncIteration to end the
    async-for loop in ``_listen()``.
    """
    mock_ws = AsyncMock()
    side_effects: list[object] = list(messages) + [StopAsyncIteration()]
    mock_ws.__aiter__ = lambda self: self
    mock_ws.__anext__ = AsyncMock(side_effect=side_effects)
    mock_ws.close = AsyncMock()
    return mock_ws


def _make_connect_cm(mock_ws: AsyncMock) -> AsyncMock:
    """Wrap a mock WebSocket in an async context manager for websockets.connect."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_ws)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _kline_json(
    interval: str = "1m",
    timestamp_ms: int = 1704067200000,
    open_price: float = 42000.0,
    high: float = 42500.0,
    low: float = 41500.0,
    close: float = 42200.0,
    volume: float = 150.0,
    is_closed: bool = True,
) -> str:
    """Build a JSON-serialized Binance kline message."""
    return json.dumps(
        {
            "e": "kline",
            "E": timestamp_ms + 1000,
            "s": "BTCUSDT",
            "k": {
                "t": timestamp_ms,
                "T": timestamp_ms + 59999,
                "s": "BTCUSDT",
                "i": interval,
                "o": str(open_price),
                "c": str(close),
                "h": str(high),
                "l": str(low),
                "v": str(volume),
                "x": is_closed,
            },
        }
    )


# --- Symbol conversion tests ---


class TestSymbolConversion:
    def test_standard_futures_symbol(self):
        assert _symbol_to_binance("BTC/USDT:USDT") == "btcusdt"

    def test_spot_style_symbol(self):
        assert _symbol_to_binance("ETH/USDT") == "ethusdt"

    def test_lowercase_passthrough(self):
        assert _symbol_to_binance("btc/usdt:usdt") == "btcusdt"


# --- Stream name building tests ---


class TestBuildStreamNames:
    def test_single_timeframe(self):
        streams = _build_stream_names("BTC/USDT:USDT", ["1m"])
        assert streams == ["btcusdt@kline_1m"]

    def test_multiple_timeframes(self):
        streams = _build_stream_names("BTC/USDT:USDT", ["1m", "4h", "1d"])
        assert streams == [
            "btcusdt@kline_1m",
            "btcusdt@kline_4h",
            "btcusdt@kline_1d",
        ]

    def test_unsupported_timeframe_raises(self):
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            _build_stream_names("BTC/USDT:USDT", ["2m"])

    def test_all_supported_timeframes(self):
        all_tfs = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
        streams = _build_stream_names("BTC/USDT:USDT", all_tfs)
        assert len(streams) == 7
        for stream in streams:
            assert stream.startswith("btcusdt@kline_")


# --- WebSocket URL building tests ---


class TestBuildWsUrl:
    def test_single_stream(self):
        url = _build_ws_url(["btcusdt@kline_1m"])
        assert url == f"{BINANCE_FUTURES_WS}/btcusdt@kline_1m"

    def test_combined_streams(self):
        url = _build_ws_url(["btcusdt@kline_1m", "btcusdt@kline_4h"])
        assert url == f"{BINANCE_FUTURES_WS}/btcusdt@kline_1m/btcusdt@kline_4h"


# --- Kline message parsing tests ---


class TestParseKlineMessage:
    def _make_kline_msg(
        self,
        interval: str = "1m",
        timestamp_ms: int = 1704067200000,
        open_price: float = 42000.0,
        high: float = 42500.0,
        low: float = 41500.0,
        close: float = 42200.0,
        volume: float = 150.0,
        is_closed: bool = True,
    ) -> dict:
        return {
            "e": "kline",
            "E": timestamp_ms + 1000,
            "s": "BTCUSDT",
            "k": {
                "t": timestamp_ms,
                "T": timestamp_ms + 59999,
                "s": "BTCUSDT",
                "i": interval,
                "o": str(open_price),
                "c": str(close),
                "h": str(high),
                "l": str(low),
                "v": str(volume),
                "x": is_closed,
            },
        }

    def test_parse_closed_candle(self):
        msg = self._make_kline_msg(is_closed=True)
        result = _parse_kline_message(msg)
        assert result is not None
        tf, candle, is_closed = result
        assert tf == "1m"
        assert is_closed is True
        assert candle.open == 42000.0
        assert candle.high == 42500.0
        assert candle.low == 41500.0
        assert candle.close == 42200.0
        assert candle.volume == 150.0
        assert candle.timestamp == datetime(2024, 1, 1, 0, 0, tzinfo=UTC)

    def test_parse_open_candle(self):
        msg = self._make_kline_msg(is_closed=False)
        result = _parse_kline_message(msg)
        assert result is not None
        _, _, is_closed = result
        assert is_closed is False

    def test_parse_bullish_candle_cvd(self):
        msg = self._make_kline_msg(open_price=100.0, close=110.0, volume=50.0)
        result = _parse_kline_message(msg)
        assert result is not None
        _, candle, _ = result
        # Bullish: cvd = 50 * 1 = 50
        assert candle.cvd == 50.0

    def test_parse_bearish_candle_cvd(self):
        msg = self._make_kline_msg(open_price=110.0, close=100.0, volume=50.0)
        result = _parse_kline_message(msg)
        assert result is not None
        _, candle, _ = result
        # Bearish: cvd = 50 * -1 = -50
        assert candle.cvd == -50.0

    def test_parse_doji_candle_cvd(self):
        msg = self._make_kline_msg(open_price=100.0, close=100.0, volume=50.0)
        result = _parse_kline_message(msg)
        assert result is not None
        _, candle, _ = result
        # Doji: cvd = 50 * 0 = 0
        assert candle.cvd == 0.0

    def test_parse_4h_timeframe(self):
        msg = self._make_kline_msg(interval="4h")
        result = _parse_kline_message(msg)
        assert result is not None
        tf, _, _ = result
        assert tf == "4h"

    def test_parse_1d_timeframe(self):
        msg = self._make_kline_msg(interval="1d")
        result = _parse_kline_message(msg)
        assert result is not None
        tf, _, _ = result
        assert tf == "1d"

    def test_parse_non_kline_event_returns_none(self):
        msg = {"e": "trade", "s": "BTCUSDT"}
        assert _parse_kline_message(msg) is None

    def test_parse_missing_kline_data_returns_none(self):
        msg = {"e": "kline"}
        assert _parse_kline_message(msg) is None

    def test_parse_unknown_interval_returns_none(self):
        msg = self._make_kline_msg(interval="3m")
        assert _parse_kline_message(msg) is None

    def test_parse_empty_dict_returns_none(self):
        assert _parse_kline_message({}) is None


# --- LiveDataProvider unit tests ---


class TestLiveDataProvider:
    def test_init_default_symbol(self, monkeypatch):
        monkeypatch.setattr("src.data.live.settings.symbol", "BTC/USDT:USDT")
        provider = LiveDataProvider()
        assert provider.symbol == "BTC/USDT:USDT"
        assert provider._ws is None
        assert provider._running is False

    def test_init_custom_symbol(self):
        provider = LiveDataProvider(symbol="ETH/USDT:USDT")
        assert provider.symbol == "ETH/USDT:USDT"

    def test_is_connected_false_initially(self):
        provider = LiveDataProvider()
        assert provider.is_connected is False


class TestLiveDataProviderSubscribe:
    """Test subscribe/unsubscribe and reconnection logic."""

    @pytest.mark.asyncio(loop_scope="function")
    async def test_subscribe_calls_callback_on_closed_candle(self):
        """Verify that the callback is invoked with the correct data when a candle closes."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        received: list[tuple[str, Candle]] = []

        async def mock_callback(tf: str, candle: Candle) -> None:
            received.append((tf, candle))
            provider._running = False

        msg = _kline_json(close=42200.0, volume=150.0, is_closed=True)
        mock_ws = _make_mock_ws([msg])
        cm = _make_connect_cm(mock_ws)

        with patch("src.data.live.websockets.connect", return_value=cm):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert len(received) == 1
        tf, candle = received[0]
        assert tf == "1m"
        assert candle.open == 42000.0
        assert candle.close == 42200.0
        assert candle.volume == 150.0
        # CVD should be cumulative (bullish: 150 * 1 = 150)
        assert candle.cvd == 150.0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_subscribe_skips_open_candles(self):
        """Verify that open (non-closed) candles don't trigger the callback."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        received: list[tuple[str, Candle]] = []

        async def mock_callback(tf: str, candle: Candle) -> None:
            received.append((tf, candle))

        msg = _kline_json(is_closed=False)
        mock_ws = _make_mock_ws([msg])
        cm = _make_connect_cm(mock_ws)

        # No callback fires for open candles, so stop after first reconnect attempt
        async def stop_on_sleep(duration: float) -> None:
            provider._running = False

        with (
            patch("src.data.live.websockets.connect", return_value=cm),
            patch("src.data.live.asyncio.sleep", side_effect=stop_on_sleep),
        ):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert len(received) == 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_subscribe_handles_non_json(self):
        """Verify graceful handling of non-JSON messages."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        received: list[tuple[str, Candle]] = []

        async def mock_callback(tf: str, candle: Candle) -> None:
            received.append((tf, candle))

        mock_ws = _make_mock_ws(["not json at all"])
        cm = _make_connect_cm(mock_ws)

        async def stop_on_sleep(duration: float) -> None:
            provider._running = False

        with (
            patch("src.data.live.websockets.connect", return_value=cm),
            patch("src.data.live.asyncio.sleep", side_effect=stop_on_sleep),
        ):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert len(received) == 0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_subscribe_handles_combined_stream_format(self):
        """Verify parsing of combined stream message format (wrapped in {stream, data})."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        received: list[tuple[str, Candle]] = []

        async def mock_callback(tf: str, candle: Candle) -> None:
            received.append((tf, candle))
            provider._running = False

        combined_msg = json.dumps(
            {
                "stream": "btcusdt@kline_1m",
                "data": {
                    "e": "kline",
                    "E": 1704067261000,
                    "s": "BTCUSDT",
                    "k": {
                        "t": 1704067200000,
                        "T": 1704067259999,
                        "s": "BTCUSDT",
                        "i": "1m",
                        "o": "42000.0",
                        "c": "42200.0",
                        "h": "42500.0",
                        "l": "41500.0",
                        "v": "150.0",
                        "x": True,
                    },
                },
            }
        )

        mock_ws = _make_mock_ws([combined_msg])
        cm = _make_connect_cm(mock_ws)

        with patch("src.data.live.websockets.connect", return_value=cm):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert len(received) == 1

    @pytest.mark.asyncio(loop_scope="function")
    async def test_cumulative_cvd_across_candles(self):
        """Verify CVD accumulates across multiple closed candles."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        received: list[tuple[str, Candle]] = []

        async def mock_callback(tf: str, candle: Candle) -> None:
            received.append((tf, candle))
            if len(received) >= 3:
                provider._running = False

        # 3 bullish candles: each has CVD delta = 100 * 1 = 100
        messages = []
        for i in range(3):
            ts = 1704067200000 + i * 60000
            messages.append(
                _kline_json(
                    timestamp_ms=ts,
                    open_price=42000.0,
                    close=42100.0,
                    high=42200.0,
                    low=41900.0,
                    volume=100.0,
                    is_closed=True,
                )
            )

        mock_ws = _make_mock_ws(messages)
        cm = _make_connect_cm(mock_ws)

        with patch("src.data.live.websockets.connect", return_value=cm):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert len(received) == 3
        # CVD should accumulate: 100, 200, 300
        assert received[0][1].cvd == 100.0
        assert received[1][1].cvd == 200.0
        assert received[2][1].cvd == 300.0

    @pytest.mark.asyncio(loop_scope="function")
    async def test_multiple_timeframe_subscription(self):
        """Verify receiving candles from multiple timeframes."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        received: list[tuple[str, Candle]] = []

        async def mock_callback(tf: str, candle: Candle) -> None:
            received.append((tf, candle))
            if len(received) >= 2:
                provider._running = False

        ts = 1704067200000
        msg_1m = _kline_json(interval="1m", timestamp_ms=ts, volume=100.0)
        msg_4h = _kline_json(
            interval="4h",
            timestamp_ms=ts,
            open_price=41000.0,
            close=42500.0,
            high=43000.0,
            low=40500.0,
            volume=5000.0,
        )

        mock_ws = _make_mock_ws([msg_1m, msg_4h])
        cm = _make_connect_cm(mock_ws)

        with patch("src.data.live.websockets.connect", return_value=cm):
            await provider.subscribe("BTC/USDT:USDT", ["1m", "4h"], mock_callback)

        assert len(received) == 2
        tfs = {r[0] for r in received}
        assert "1m" in tfs
        assert "4h" in tfs

    @pytest.mark.asyncio(loop_scope="function")
    async def test_reconnect_on_connection_error(self):
        """Verify auto-reconnect with exponential backoff after connection failure."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        connect_attempts = 0

        async def mock_callback(tf: str, candle: Candle) -> None:
            pass

        cm_fail = AsyncMock()
        cm_fail.__aenter__ = AsyncMock(side_effect=OSError("Connection refused"))
        cm_fail.__aexit__ = AsyncMock(return_value=False)

        async def mock_sleep(duration: float) -> None:
            nonlocal connect_attempts
            connect_attempts += 1
            if connect_attempts >= 3:
                provider._running = False

        with (
            patch("src.data.live.websockets.connect", return_value=cm_fail),
            patch("src.data.live.asyncio.sleep", side_effect=mock_sleep),
        ):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert connect_attempts >= 3

    @pytest.mark.asyncio(loop_scope="function")
    async def test_stops_after_max_consecutive_failures(self):
        """Verify the provider stops after MAX_CONSECUTIVE_FAILURES."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")

        async def mock_callback(tf: str, candle: Candle) -> None:
            pass

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=OSError("Connection refused"))
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.data.live.websockets.connect", return_value=cm),
            patch("src.data.live.asyncio.sleep", new_callable=AsyncMock),
        ):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], mock_callback)

        assert provider._running is False
        assert provider._consecutive_failures >= MAX_CONSECUTIVE_FAILURES


class TestLiveDataProviderUnsubscribe:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_unsubscribe_cleans_up(self):
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        provider._running = True
        provider._cvd_accumulator = {"1m": 100.0}

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        provider._ws = mock_ws

        await provider.unsubscribe()

        assert provider._running is False
        assert provider._ws is None
        assert provider._cvd_accumulator == {}
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unsubscribe_safe_when_not_connected(self):
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        await provider.unsubscribe()
        assert provider._running is False

    @pytest.mark.asyncio(loop_scope="function")
    async def test_unsubscribe_handles_close_error(self):
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        provider._running = True

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("close error"))
        provider._ws = mock_ws

        await provider.unsubscribe()
        assert provider._ws is None


class TestLiveDataProviderHistorical:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_get_historical_candles_delegates(self):
        """Verify get_historical_candles delegates to HistoricalDataProvider."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")

        expected_candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=42000.0,
                high=42500.0,
                low=41500.0,
                close=42200.0,
                volume=100.0,
            )
        ]

        mock_historical = AsyncMock()
        mock_historical.get_historical_candles = AsyncMock(return_value=expected_candles)
        mock_historical.close = AsyncMock()

        with patch(
            "src.data.historical.HistoricalDataProvider",
            return_value=mock_historical,
        ):
            result = await provider.get_historical_candles(
                "BTC/USDT:USDT",
                "1m",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
            )

        assert result == expected_candles
        mock_historical.get_historical_candles.assert_called_once()
        mock_historical.close.assert_called_once()


class TestCallbackErrorHandling:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_callback_error_does_not_crash_provider(self):
        """Verify that an exception in the callback doesn't kill the listener."""
        provider = LiveDataProvider(symbol="BTC/USDT:USDT")
        call_count = 0

        async def failing_callback(tf: str, candle: Candle) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("callback error")
            provider._running = False

        ts = 1704067200000
        messages = [
            _kline_json(
                timestamp_ms=ts + i * 60000,
                open_price=42000.0,
                close=42100.0,
                high=42200.0,
                low=41900.0,
                volume=100.0,
                is_closed=True,
            )
            for i in range(2)
        ]

        mock_ws = _make_mock_ws(messages)
        cm = _make_connect_cm(mock_ws)

        with patch("src.data.live.websockets.connect", return_value=cm):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], failing_callback)

        # Both candles should have been processed despite the error on the first
        assert call_count == 2
