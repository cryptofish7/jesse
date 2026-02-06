"""Tests for the data layer: cache, orderflow, and historical provider."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.core.types import Candle
from src.data import cache, orderflow
from src.data.historical import HistoricalDataProvider

# --- Helpers ---


def _make_candle(ts_hour: int, close: float = 100.0, volume: float = 10.0, **kw) -> Candle:
    return Candle(
        timestamp=datetime(2024, 1, 1, ts_hour, tzinfo=UTC),
        open=100.0,
        high=110.0,
        low=90.0,
        close=close,
        volume=volume,
        **kw,
    )


# --- Cache Tests ---


class TestCache:
    def test_cache_path_generation(self):
        p = cache.cache_path("BTC/USDT:USDT", "1m")
        assert "BTC_USDT_USDT_1m.parquet" in str(p)

    def test_cache_exists_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        assert cache.cache_exists("BTC/USDT:USDT", "1m") is False

    def test_write_and_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        candles = [_make_candle(i) for i in range(5)]
        cache.write_candles("BTC/USDT:USDT", "1m", candles)

        assert cache.cache_exists("BTC/USDT:USDT", "1m") is True

        loaded = cache.read_candles("BTC/USDT:USDT", "1m")
        assert len(loaded) == 5
        assert loaded[0].timestamp == candles[0].timestamp
        assert loaded[0].open == candles[0].open

    def test_read_empty_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        result = cache.read_candles("BTC/USDT:USDT", "1m")
        assert result == []

    def test_write_empty_list_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        cache.write_candles("BTC/USDT:USDT", "1m", [])
        assert cache.cache_exists("BTC/USDT:USDT", "1m") is False

    def test_cache_date_range(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        candles = [_make_candle(i) for i in range(5)]
        cache.write_candles("BTC/USDT:USDT", "1m", candles)

        result = cache.get_cache_date_range("BTC/USDT:USDT", "1m")
        assert result is not None
        assert result[0] == candles[0].timestamp
        assert result[1] == candles[-1].timestamp

    def test_cache_date_range_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        assert cache.get_cache_date_range("BTC/USDT:USDT", "1m") is None

    def test_merge_candles_deduplicates(self):
        existing = [_make_candle(0), _make_candle(1), _make_candle(2)]
        new = [_make_candle(1, close=200.0), _make_candle(3)]
        merged = cache.merge_candles(existing, new)
        assert len(merged) == 4
        # New values override existing for same timestamp
        assert merged[1].close == 200.0
        # Sorted by timestamp
        assert merged[-1].timestamp.hour == 3

    def test_merge_candles_empty_inputs(self):
        assert cache.merge_candles([], []) == []
        candles = [_make_candle(0)]
        assert cache.merge_candles(candles, []) == candles
        assert cache.merge_candles([], candles) == candles


# --- Orderflow Tests ---


class TestOrderflow:
    def test_approximate_cvd_bullish(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=100.0,
            ),
        ]
        result = orderflow.approximate_cvd(candles)
        assert len(result) == 1
        # Bullish candle: cvd = 100 * 1 = 100
        assert result[0].cvd == 100.0

    def test_approximate_cvd_bearish(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=105.0,
                high=110.0,
                low=90.0,
                close=100.0,
                volume=100.0,
            ),
        ]
        result = orderflow.approximate_cvd(candles)
        assert result[0].cvd == -100.0

    def test_approximate_cvd_doji(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=110.0,
                low=90.0,
                close=100.0,
                volume=100.0,
            ),
        ]
        result = orderflow.approximate_cvd(candles)
        assert result[0].cvd == 0.0

    def test_approximate_cvd_cumulative(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, 0, tzinfo=UTC),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=100.0,
            ),
            Candle(
                timestamp=datetime(2024, 1, 1, 1, tzinfo=UTC),
                open=105.0,
                high=110.0,
                low=90.0,
                close=103.0,
                volume=50.0,
            ),
        ]
        result = orderflow.approximate_cvd(candles)
        # First: +100, second: -50 => cumulative = 50
        assert result[0].cvd == 100.0
        assert result[1].cvd == 50.0

    def test_approximate_cvd_preserves_existing(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=100.0,
                cvd=42.0,
            ),
        ]
        result = orderflow.approximate_cvd(candles)
        assert result[0].cvd == 42.0

    def test_enrich_with_oi(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=100.0,
            ),
        ]
        ts_ms = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
        oi_data = {ts_ms: 5000.0}
        result = orderflow.enrich_with_oi(candles, oi_data)
        assert result[0].open_interest == 5000.0

    def test_enrich_with_oi_no_match(self):
        candles = [
            Candle(
                timestamp=datetime(2024, 1, 1, tzinfo=UTC),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=100.0,
                open_interest=0.0,
            ),
        ]
        result = orderflow.enrich_with_oi(candles, {})
        assert result[0].open_interest == 0.0


# --- HistoricalDataProvider Tests ---


class TestHistoricalDataProvider:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_fetch_uses_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))

        # Pre-populate cache
        candles = [_make_candle(i) for i in range(5)]
        cache.write_candles("BTC/USDT:USDT", "1m", candles)

        provider = HistoricalDataProvider()
        result = await provider.get_historical_candles(
            "BTC/USDT:USDT",
            "1m",
            datetime(2024, 1, 1, 0, tzinfo=UTC),
            datetime(2024, 1, 1, 4, tzinfo=UTC),
        )
        assert len(result) == 5
        # No exchange call needed

    @pytest.mark.asyncio(loop_scope="function")
    async def test_fetch_from_exchange(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))

        # Mock the exchange
        mock_exchange = AsyncMock()
        mock_ohlcv = [
            [
                int(datetime(2024, 1, 1, i, tzinfo=UTC).timestamp() * 1000),
                100.0,
                110.0,
                90.0,
                105.0,
                1000.0,
            ]
            for i in range(3)
        ]
        mock_exchange.fetch_ohlcv = AsyncMock(side_effect=[mock_ohlcv, []])

        provider = HistoricalDataProvider()
        provider._exchange = mock_exchange

        result = await provider.get_historical_candles(
            "BTC/USDT:USDT",
            "1m",
            datetime(2024, 1, 1, 0, tzinfo=UTC),
            datetime(2024, 1, 1, 3, tzinfo=UTC),
        )
        assert len(result) == 3
        assert result[0].close == 105.0
        # CVD should be computed
        assert result[0].cvd != 0.0

        # Should be cached now
        assert cache.cache_exists("BTC/USDT:USDT", "1m")

    @pytest.mark.asyncio(loop_scope="function")
    async def test_invalid_timeframe_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.data.cache.settings.cache_path", str(tmp_path))
        provider = HistoricalDataProvider()
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            await provider.get_historical_candles(
                "BTC/USDT:USDT",
                "2m",
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 1, 2, tzinfo=UTC),
            )

    @pytest.mark.asyncio(loop_scope="function")
    async def test_subscribe_raises(self):
        provider = HistoricalDataProvider()
        with pytest.raises(NotImplementedError):
            await provider.subscribe("BTC/USDT:USDT", ["1m"], AsyncMock())


# --- Exchange Creation Tests ---


class TestCreateExchange:
    """Test exchange creation with credentials."""

    def test_creates_exchange_with_credentials(self, monkeypatch):
        monkeypatch.setattr("src.data.historical.settings.exchange", "binance")
        monkeypatch.setattr("src.data.historical.settings.api_key", "test-key")
        monkeypatch.setattr("src.data.historical.settings.api_secret", "test-secret")

        from src.data.historical import _create_exchange

        exchange = _create_exchange()
        assert exchange.apiKey == "test-key"
        assert exchange.secret == "test-secret"

    def test_raises_without_credentials(self, monkeypatch):
        monkeypatch.setattr("src.data.historical.settings.exchange", "binance")
        monkeypatch.setattr("src.data.historical.settings.api_key", "")
        monkeypatch.setattr("src.data.historical.settings.api_secret", "")

        from src.data.historical import _create_exchange

        with pytest.raises(ValueError, match="API credentials required"):
            _create_exchange()
