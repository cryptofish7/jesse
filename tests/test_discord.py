"""Tests for DiscordAlerter — message formatting, webhook calls, and rate limiting."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.alerts.discord import COLOR_BLUE, COLOR_GREEN, COLOR_RED, DiscordAlerter
from src.core.types import Position, Trade

# --- Helpers ---

WEBHOOK_URL = "https://discord.com/api/webhooks/123456/test-token"


def _position(
    id_: str = "pos-001",
    side: str = "long",
    entry_price: float = 50_000.0,
    size: float = 0.02,
    size_usd: float = 1_000.0,
    stop_loss: float = 48_000.0,
    take_profit: float = 55_000.0,
) -> Position:
    return Position(
        id=id_,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        entry_time=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        size=size,
        size_usd=size_usd,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def _trade(
    id_: str = "trade-001",
    side: str = "long",
    entry_price: float = 50_000.0,
    exit_price: float = 55_000.0,
    pnl: float = 100.0,
    pnl_percent: float = 10.0,
    exit_reason: str = "take_profit",
) -> Trade:
    return Trade(
        id=id_,
        side=side,  # type: ignore[arg-type]
        entry_price=entry_price,
        exit_price=exit_price,
        entry_time=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        exit_time=datetime(2024, 6, 1, 14, 0, 0, tzinfo=UTC),
        size=0.02,
        size_usd=1_000.0,
        pnl=pnl,
        pnl_percent=pnl_percent,
        exit_reason=exit_reason,  # type: ignore[arg-type]
    )


def _mock_response(
    status_code: int = 204,
    headers: dict | None = None,
    json_data: dict | None = None,
) -> httpx.Response:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = ""
    resp.json.return_value = json_data or {}
    return resp


# --- TestSendAlert ---


class TestSendAlert:
    """Tests for the core send_alert method."""

    def setup_method(self) -> None:
        self.alerter = DiscordAlerter(WEBHOOK_URL)
        self.alerter._client = MagicMock(spec=httpx.AsyncClient)
        self.mock_post = AsyncMock(return_value=_mock_response(204))
        self.alerter._client.post = self.mock_post

    @pytest.mark.asyncio
    async def test_send_message_only(self) -> None:
        await self.alerter.send_alert("Hello world")

        self.mock_post.assert_called_once_with(
            WEBHOOK_URL,
            json={"content": "Hello world"},
        )

    @pytest.mark.asyncio
    async def test_send_with_embed(self) -> None:
        embed = {"title": "Test", "color": 123}
        await self.alerter.send_alert("msg", embed=embed)

        self.mock_post.assert_called_once_with(
            WEBHOOK_URL,
            json={"content": "msg", "embeds": [embed]},
        )

    @pytest.mark.asyncio
    async def test_no_embed_key_when_none(self) -> None:
        await self.alerter.send_alert("msg", embed=None)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        assert "embeds" not in payload

    @pytest.mark.asyncio
    async def test_http_error_logged_not_raised(self) -> None:
        """HTTP errors are logged but not raised."""
        self.mock_post.side_effect = httpx.ConnectError("connection refused")

        # Should not raise
        await self.alerter.send_alert("test")

    @pytest.mark.asyncio
    async def test_non_200_logged_not_raised(self) -> None:
        """Non-success status codes are logged but do not raise."""
        self.mock_post.return_value = _mock_response(500)

        # Should not raise
        await self.alerter.send_alert("test")


# --- TestRateLimiting ---


class TestRateLimiting:
    """Tests for Discord 429 rate limit handling."""

    def setup_method(self) -> None:
        self.alerter = DiscordAlerter(WEBHOOK_URL)
        self.alerter._client = MagicMock(spec=httpx.AsyncClient)

    @pytest.mark.asyncio
    async def test_retries_on_429_with_retry_after_header(self) -> None:
        """On 429, sleeps for Retry-After seconds and retries."""
        rate_limited = _mock_response(429, headers={"Retry-After": "0.01"})
        success = _mock_response(204)

        self.alerter._client.post = AsyncMock(side_effect=[rate_limited, success])

        with patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
            await self.alerter.send_alert("test")

        mock_sleep.assert_called_once_with(0.01)
        assert self.alerter._client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_429_with_json_retry_after(self) -> None:
        """On 429, falls back to JSON body retry_after if no header."""
        rate_limited = _mock_response(429, headers={}, json_data={"retry_after": 0.02})
        success = _mock_response(204)

        self.alerter._client.post = AsyncMock(side_effect=[rate_limited, success])

        with patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
            await self.alerter.send_alert("test")

        mock_sleep.assert_called_once_with(0.02)

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self) -> None:
        """After _MAX_RATE_LIMIT_RETRIES 429s, drops the message."""
        rate_limited = _mock_response(429, headers={"Retry-After": "0.01"})

        # 4 responses: all 429 (initial + 3 retries)
        self.alerter._client.post = AsyncMock(
            side_effect=[rate_limited, rate_limited, rate_limited, rate_limited]
        )

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            await self.alerter.send_alert("test")

        # Initial + 3 retries = 4 calls
        assert self.alerter._client.post.call_count == 4

    @pytest.mark.asyncio
    async def test_default_retry_after_when_unparseable(self) -> None:
        """Falls back to 1.0s if Retry-After header is unparseable."""
        rate_limited = _mock_response(429, headers={"Retry-After": "invalid"})
        rate_limited.json.side_effect = Exception("no json")
        success = _mock_response(204)

        self.alerter._client.post = AsyncMock(side_effect=[rate_limited, success])

        with patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
            await self.alerter.send_alert("test")

        mock_sleep.assert_called_once_with(1.0)


# --- TestOnStrategyStart ---


class TestOnStrategyStart:
    """Tests for on_strategy_start formatting."""

    def setup_method(self) -> None:
        self.alerter = DiscordAlerter(WEBHOOK_URL)
        self.alerter._client = MagicMock(spec=httpx.AsyncClient)
        self.mock_post = AsyncMock(return_value=_mock_response(204))
        self.alerter._client.post = self.mock_post

    @pytest.mark.asyncio
    async def test_strategy_start_embed(self) -> None:
        await self.alerter.on_strategy_start("MACrossover")

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert embed["title"] == "Strategy Started"
        assert "MACrossover" in embed["description"]
        assert embed["color"] == COLOR_BLUE
        assert "timestamp" in embed


# --- TestOnTradeOpen ---


class TestOnTradeOpen:
    """Tests for on_trade_open formatting."""

    def setup_method(self) -> None:
        self.alerter = DiscordAlerter(WEBHOOK_URL)
        self.alerter._client = MagicMock(spec=httpx.AsyncClient)
        self.mock_post = AsyncMock(return_value=_mock_response(204))
        self.alerter._client.post = self.mock_post

    @pytest.mark.asyncio
    async def test_long_position_embed(self) -> None:
        pos = _position(side="long", entry_price=50_000.0, stop_loss=48_000.0, take_profit=55_000.0)
        await self.alerter.on_trade_open(pos)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert "LONG" in embed["title"]
        assert embed["color"] == COLOR_GREEN
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert fields["Side"] == "LONG"
        assert "$50,000.00" in fields["Entry Price"]
        assert "$48,000.00" in fields["Stop Loss"]
        assert "$55,000.00" in fields["Take Profit"]
        assert "timestamp" in embed

    @pytest.mark.asyncio
    async def test_short_position_embed(self) -> None:
        pos = _position(side="short")
        await self.alerter.on_trade_open(pos)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert "SHORT" in embed["title"]
        assert embed["color"] == COLOR_RED


# --- TestOnTradeClose ---


class TestOnTradeClose:
    """Tests for on_trade_close formatting."""

    def setup_method(self) -> None:
        self.alerter = DiscordAlerter(WEBHOOK_URL)
        self.alerter._client = MagicMock(spec=httpx.AsyncClient)
        self.mock_post = AsyncMock(return_value=_mock_response(204))
        self.alerter._client.post = self.mock_post

    @pytest.mark.asyncio
    async def test_profitable_trade_embed(self) -> None:
        trade = _trade(pnl=100.0, pnl_percent=10.0, exit_reason="take_profit")
        await self.alerter.on_trade_close(trade)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert "Take Profit" in embed["title"]
        assert embed["color"] == COLOR_GREEN
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "+$100.00" in fields["PnL"]  # sign before dollar
        assert "+10.00%" in fields["PnL"]

    @pytest.mark.asyncio
    async def test_losing_trade_embed(self) -> None:
        trade = _trade(pnl=-50.0, pnl_percent=-5.0, exit_reason="stop_loss")
        await self.alerter.on_trade_close(trade)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert "Stop Loss" in embed["title"]
        assert embed["color"] == COLOR_RED
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "-$50.00" in fields["PnL"]  # sign before dollar
        assert "-5.00%" in fields["PnL"]

    @pytest.mark.asyncio
    async def test_signal_close_embed(self) -> None:
        trade = _trade(exit_reason="signal")
        await self.alerter.on_trade_close(trade)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert "Signal" in embed["title"]

    @pytest.mark.asyncio
    async def test_breakeven_trade_uses_green(self) -> None:
        trade = _trade(pnl=0.0, pnl_percent=0.0)
        await self.alerter.on_trade_close(trade)

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert embed["color"] == COLOR_GREEN  # pnl >= 0


# --- TestOnError ---


class TestOnError:
    """Tests for on_error formatting."""

    def setup_method(self) -> None:
        self.alerter = DiscordAlerter(WEBHOOK_URL)
        self.alerter._client = MagicMock(spec=httpx.AsyncClient)
        self.mock_post = AsyncMock(return_value=_mock_response(204))
        self.alerter._client.post = self.mock_post

    @pytest.mark.asyncio
    async def test_error_embed(self) -> None:
        await self.alerter.on_error("WebSocket disconnected")

        call_kwargs = self.mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1]["json"]
        embed = payload["embeds"][0]

        assert embed["title"] == "Error"
        assert "WebSocket disconnected" in embed["description"]
        assert embed["color"] == COLOR_RED
        assert "timestamp" in embed


# --- TestClose ---


class TestAlerterClose:
    """Tests for the close() method."""

    @pytest.mark.asyncio
    async def test_close_calls_aclose(self) -> None:
        alerter = DiscordAlerter(WEBHOOK_URL)
        alerter._client = MagicMock(spec=httpx.AsyncClient)
        alerter._client.aclose = AsyncMock()

        await alerter.close()

        alerter._client.aclose.assert_called_once()


# --- TestParseRetryAfter ---


class TestParseRetryAfter:
    """Tests for _parse_retry_after static method."""

    def test_header_value(self) -> None:
        resp = _mock_response(429, headers={"Retry-After": "2.5"})
        assert DiscordAlerter._parse_retry_after(resp) == 2.5

    def test_json_body_fallback(self) -> None:
        resp = _mock_response(429, headers={}, json_data={"retry_after": 1.5})
        assert DiscordAlerter._parse_retry_after(resp) == 1.5

    def test_default_fallback(self) -> None:
        resp = _mock_response(429, headers={})
        resp.json.side_effect = Exception("no json")
        assert DiscordAlerter._parse_retry_after(resp) == 1.0

    def test_invalid_header_uses_json(self) -> None:
        resp = _mock_response(
            429, headers={"Retry-After": "not-a-number"}, json_data={"retry_after": 3.0}
        )
        assert DiscordAlerter._parse_retry_after(resp) == 3.0


# --- TestEngineAlerterIntegration ---


class TestEngineAlerterIntegration:
    """Tests that Engine calls alerter methods at the right points."""

    @pytest.mark.asyncio
    async def test_engine_calls_alerter_on_strategy_start(self) -> None:
        """Engine calls on_strategy_start when run_backtest begins."""
        from unittest.mock import AsyncMock as AM

        from src.core.engine import Engine

        # Minimal mock setup
        mock_alerter = MagicMock()
        mock_alerter.on_strategy_start = AM()
        mock_alerter.on_error = AM()

        mock_strategy = MagicMock()
        mock_strategy.timeframes = ["1m"]
        mock_strategy.on_candle.return_value = []

        mock_provider = MagicMock()
        mock_provider.get_historical_candles = AM(return_value=[])

        from src.execution.backtest import BacktestExecutor

        executor = BacktestExecutor(initial_balance=10_000.0)

        engine = Engine(
            strategy=mock_strategy,
            data_provider=mock_provider,
            executor=executor,
            alerter=mock_alerter,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        # Fake a symbol
        mock_provider.symbol = "BTC/USDT:USDT"

        await engine.run_backtest()

        mock_alerter.on_strategy_start.assert_called_once()
        call_args = mock_alerter.on_strategy_start.call_args[0]
        assert call_args[0] == "MagicMock"  # type(mock_strategy).__name__

    @pytest.mark.asyncio
    async def test_engine_calls_alerter_on_error(self) -> None:
        """Engine calls on_error when run() raises."""
        from unittest.mock import AsyncMock as AM

        from src.core.engine import Engine

        mock_alerter = MagicMock()
        mock_alerter.on_strategy_start = AM()
        mock_alerter.on_error = AM()

        mock_strategy = MagicMock()
        mock_strategy.timeframes = ["1m"]

        mock_provider = MagicMock()
        mock_provider.symbol = "BTC/USDT:USDT"
        mock_provider.get_historical_candles = AM(side_effect=ValueError("test error"))

        from src.execution.backtest import BacktestExecutor

        executor = BacktestExecutor(initial_balance=10_000.0)

        engine = Engine(
            strategy=mock_strategy,
            data_provider=mock_provider,
            executor=executor,
            alerter=mock_alerter,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="test error"):
            await engine.run()

        mock_alerter.on_error.assert_called_once()
        error_msg = mock_alerter.on_error.call_args[0][0]
        assert "ValueError" in error_msg
        assert "test error" in error_msg

    @pytest.mark.asyncio
    async def test_engine_no_alerter_does_not_crash(self) -> None:
        """Engine runs fine without an alerter (alerter=None)."""
        from unittest.mock import AsyncMock as AM

        from src.core.engine import Engine
        from src.execution.backtest import BacktestExecutor

        mock_strategy = MagicMock()
        mock_strategy.timeframes = ["1m"]
        mock_strategy.on_candle.return_value = []

        mock_provider = MagicMock()
        mock_provider.symbol = "BTC/USDT:USDT"
        mock_provider.get_historical_candles = AM(return_value=[])

        executor = BacktestExecutor(initial_balance=10_000.0)

        engine = Engine(
            strategy=mock_strategy,
            data_provider=mock_provider,
            executor=executor,
            alerter=None,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        result = await engine.run_backtest()
        assert result is not None  # should return empty BacktestResults
