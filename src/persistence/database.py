"""Async SQLite database for persistence — positions, trades, portfolio, strategy state."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from src.core.portfolio import Portfolio
from src.core.types import Position, Trade
from src.persistence.models import ALL_TABLES

logger = logging.getLogger(__name__)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC).

    SQLite stores datetimes as plain ISO strings, stripping tzinfo.
    When reading back we must re-attach UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class Database:
    """Async SQLite database for Jesse persistence.

    Uses aiosqlite for non-blocking I/O. All datetime values are stored
    as ISO 8601 strings and re-attached with UTC on read.

    Lifecycle::

        db = Database("data/jesse.db")
        await db.initialize()   # opens connection + creates tables
        ...                     # use db methods
        await db.close()        # close when done
    """

    def __init__(self, db_path: str | Path = "data/jesse.db") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        """Return the active connection, raising if not initialized."""
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    async def initialize(self) -> None:
        """Open the connection and create all tables if they don't already exist."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        for ddl in ALL_TABLES:
            await self._conn.execute(ddl)
        await self._conn.commit()
        logger.info("Database initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # --- Positions ---

    async def save_position(self, position: Position) -> None:
        """INSERT OR REPLACE an open position."""
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO positions
                (id, side, entry_price, entry_time, size, size_usd,
                 stop_loss, take_profit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position.id,
                position.side,
                position.entry_price,
                position.entry_time.isoformat(),
                position.size,
                position.size_usd,
                position.stop_loss,
                position.take_profit,
                datetime.now(UTC).isoformat(),
            ),
        )
        await conn.commit()

    async def delete_position(self, position_id: str) -> None:
        """Delete a position by ID."""
        conn = await self._get_conn()
        await conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        await conn.commit()

    async def get_open_positions(self) -> list[Position]:
        """Return all open positions with UTC-aware datetimes."""
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT * FROM positions")
        rows = await cursor.fetchall()

        positions: list[Position] = []
        for row in rows:
            entry_time = _ensure_utc(datetime.fromisoformat(row["entry_time"]))
            positions.append(
                Position(
                    id=row["id"],
                    side=row["side"],
                    entry_price=row["entry_price"],
                    entry_time=entry_time,
                    size=row["size"],
                    size_usd=row["size_usd"],
                    stop_loss=row["stop_loss"],
                    take_profit=row["take_profit"],
                )
            )
        return positions

    # --- Trades ---

    async def save_trade(self, trade: Trade) -> None:
        """INSERT OR REPLACE a completed trade."""
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO trades
                (id, side, entry_price, exit_price, entry_time, exit_time,
                 size, size_usd, pnl, pnl_percent, exit_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.id,
                trade.side,
                trade.entry_price,
                trade.exit_price,
                trade.entry_time.isoformat(),
                trade.exit_time.isoformat(),
                trade.size,
                trade.size_usd,
                trade.pnl,
                trade.pnl_percent,
                trade.exit_reason,
                datetime.now(UTC).isoformat(),
            ),
        )
        await conn.commit()

    async def get_trades(self) -> list[Trade]:
        """Return all trades with UTC-aware datetimes."""
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT * FROM trades")
        rows = await cursor.fetchall()

        trades: list[Trade] = []
        for row in rows:
            entry_time = _ensure_utc(datetime.fromisoformat(row["entry_time"]))
            exit_time = _ensure_utc(datetime.fromisoformat(row["exit_time"]))
            trades.append(
                Trade(
                    id=row["id"],
                    side=row["side"],
                    entry_price=row["entry_price"],
                    exit_price=row["exit_price"],
                    entry_time=entry_time,
                    exit_time=exit_time,
                    size=row["size"],
                    size_usd=row["size_usd"],
                    pnl=row["pnl"],
                    pnl_percent=row["pnl_percent"],
                    exit_reason=row["exit_reason"],
                )
            )
        return trades

    # --- Portfolio ---

    async def save_portfolio(self, portfolio: Portfolio) -> None:
        """INSERT OR REPLACE the single portfolio row (id=1)."""
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO portfolio
                (id, initial_balance, balance, updated_at)
            VALUES (1, ?, ?, ?)
            """,
            (
                portfolio.initial_balance,
                portfolio.balance,
                datetime.now(UTC).isoformat(),
            ),
        )
        await conn.commit()

    async def get_portfolio(self) -> Portfolio | None:
        """Return the saved portfolio, or None if nothing persisted yet."""
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT * FROM portfolio WHERE id = 1")
        row = await cursor.fetchone()

        if row is None:
            return None

        return Portfolio(
            initial_balance=row["initial_balance"],
            balance=row["balance"],
        )

    # --- Strategy state ---

    async def save_strategy_state(self, strategy_name: str, state_dict: dict[str, Any]) -> None:
        """Serialize state as JSON and persist it."""
        conn = await self._get_conn()
        await conn.execute(
            """
            INSERT OR REPLACE INTO strategy_state
                (strategy_name, state_json, updated_at)
            VALUES (?, ?, ?)
            """,
            (
                strategy_name,
                json.dumps(state_dict),
                datetime.now(UTC).isoformat(),
            ),
        )
        await conn.commit()

    async def get_strategy_state(self, strategy_name: str) -> dict[str, Any] | None:
        """Load and deserialize strategy state. Returns None if not found."""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT state_json FROM strategy_state WHERE strategy_name = ?",
            (strategy_name,),
        )
        row = await cursor.fetchone()

        if row is None:
            return None

        result: dict[str, Any] = json.loads(row["state_json"])
        return result

    # --- Utilities ---

    async def clear_all(self) -> None:
        """Delete all data from all tables. Intended for testing."""
        conn = await self._get_conn()
        await conn.execute("DELETE FROM positions")
        await conn.execute("DELETE FROM trades")
        await conn.execute("DELETE FROM portfolio")
        await conn.execute("DELETE FROM strategy_state")
        await conn.commit()
