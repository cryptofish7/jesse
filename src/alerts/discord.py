"""Discord alerter — send trade notifications via Discord webhooks."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from src.core.types import Position, Trade

logger = logging.getLogger(__name__)

# Discord embed colors (decimal)
COLOR_GREEN = 0x2ECC71  # Long / profit
COLOR_RED = 0xE74C3C  # Short / loss / error
COLOR_BLUE = 0x3498DB  # Info / strategy start
COLOR_ORANGE = 0xE67E22  # Warning

# Maximum retries for rate-limited requests
_MAX_RATE_LIMIT_RETRIES = 3


class DiscordAlerter:
    """Send trade event notifications to a Discord channel via webhook.

    All methods are async and handle failures gracefully — they log errors
    but never raise, so the trading engine is never disrupted by alert failures.

    Rate limiting is handled automatically: if Discord returns a 429, the
    alerter waits for the ``Retry-After`` duration before retrying (up to
    ``_MAX_RATE_LIMIT_RETRIES`` times).
    """

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # --- Public alert methods ---

    async def send_alert(self, message: str, embed: dict | None = None) -> None:
        """Send a message (and optional embed) to the Discord webhook.

        Handles rate limiting (429) by sleeping for the ``Retry-After``
        duration and retrying. All HTTP and network errors are caught and
        logged — this method never raises.
        """
        payload: dict = {"content": message}
        if embed is not None:
            payload["embeds"] = [embed]

        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = await self._client.post(self.webhook_url, json=payload)

                if response.status_code == 429:
                    retry_after = self._parse_retry_after(response)
                    if attempt < _MAX_RATE_LIMIT_RETRIES:
                        logger.warning(
                            "Discord rate limited, retrying after %.1fs (attempt %d/%d)",
                            retry_after,
                            attempt + 1,
                            _MAX_RATE_LIMIT_RETRIES,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.error(
                            "Discord rate limit exceeded after %d retries, dropping message",
                            _MAX_RATE_LIMIT_RETRIES,
                        )
                        return

                if response.status_code >= 400:
                    logger.error(
                        "Discord webhook returned %d: %s",
                        response.status_code,
                        response.text[:200],
                    )
                return

            except httpx.HTTPError as exc:
                logger.error("Discord webhook request failed: %s", exc)
                return
            except Exception as exc:
                logger.error("Unexpected error sending Discord alert: %s", exc)
                return

    async def on_strategy_start(self, strategy_name: str) -> None:
        """Alert when a strategy becomes active."""
        embed = {
            "title": "Strategy Started",
            "description": f"**{strategy_name}** is now active",
            "color": COLOR_BLUE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_alert("", embed=embed)

    async def on_trade_open(self, position: Position) -> None:
        """Alert when a new position is opened."""
        side_upper = position.side.upper()
        color = COLOR_GREEN if position.side == "long" else COLOR_RED
        embed = {
            "title": f"Position Opened: {side_upper}",
            "color": color,
            "fields": [
                {"name": "Side", "value": side_upper, "inline": True},
                {
                    "name": "Entry Price",
                    "value": f"${position.entry_price:,.2f}",
                    "inline": True,
                },
                {
                    "name": "Size (USD)",
                    "value": f"${position.size_usd:,.2f}",
                    "inline": True,
                },
                {
                    "name": "Stop Loss",
                    "value": f"${position.stop_loss:,.2f}",
                    "inline": True,
                },
                {
                    "name": "Take Profit",
                    "value": f"${position.take_profit:,.2f}",
                    "inline": True,
                },
                {"name": "Position ID", "value": f"`{position.id}`", "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_alert("", embed=embed)

    async def on_trade_close(self, trade: Trade) -> None:
        """Alert when a trade is closed."""
        color = COLOR_GREEN if trade.pnl >= 0 else COLOR_RED
        pnl_str = self._format_pnl(trade.pnl)
        pnl_pct_str = self._format_pnl_percent(trade.pnl_percent)

        exit_reason_display = trade.exit_reason.replace("_", " ").title()

        embed = {
            "title": f"Trade Closed: {exit_reason_display}",
            "color": color,
            "fields": [
                {"name": "Side", "value": trade.side.upper(), "inline": True},
                {
                    "name": "Entry Price",
                    "value": f"${trade.entry_price:,.2f}",
                    "inline": True,
                },
                {
                    "name": "Exit Price",
                    "value": f"${trade.exit_price:,.2f}",
                    "inline": True,
                },
                {
                    "name": "PnL",
                    "value": f"{pnl_str} ({pnl_pct_str})",
                    "inline": True,
                },
                {"name": "Exit Reason", "value": exit_reason_display, "inline": True},
                {"name": "Trade ID", "value": f"`{trade.id}`", "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_alert("", embed=embed)

    async def on_error(self, error_message: str) -> None:
        """Alert on an error."""
        embed = {
            "title": "Error",
            "description": error_message,
            "color": COLOR_RED,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.send_alert("", embed=embed)

    # --- Private helpers ---

    @staticmethod
    def _format_pnl(pnl: float) -> str:
        """Format PnL with sign before the dollar sign: +$100.00 or -$50.00."""
        if pnl >= 0:
            return f"+${pnl:,.2f}"
        return f"-${abs(pnl):,.2f}"

    @staticmethod
    def _format_pnl_percent(pnl_percent: float) -> str:
        """Format PnL percent with sign: +10.00% or -5.00%."""
        if pnl_percent >= 0:
            return f"+{pnl_percent:.2f}%"
        return f"{pnl_percent:.2f}%"

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float:
        """Extract Retry-After seconds from a 429 response.

        Falls back to 1.0 second if the header is missing or unparseable.
        """
        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header is not None:
            try:
                return float(retry_after_header)
            except (ValueError, TypeError):
                pass

        # Try Discord's JSON body format: {"retry_after": 1.5}
        try:
            body = response.json()
            return float(body.get("retry_after", 1.0))
        except Exception:
            return 1.0
