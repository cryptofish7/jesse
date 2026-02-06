"""SQLite schema definitions for the Jesse persistence layer."""

from __future__ import annotations

SCHEMA_VERSION = 1

CREATE_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    size REAL NOT NULL,
    size_usd REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""

CREATE_TRADES_TABLE = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    size REAL NOT NULL,
    size_usd REAL NOT NULL,
    pnl REAL NOT NULL,
    pnl_percent REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

CREATE_PORTFOLIO_TABLE = """
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    initial_balance REAL NOT NULL,
    balance REAL NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_STRATEGY_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_name TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

ALL_TABLES = [
    CREATE_POSITIONS_TABLE,
    CREATE_TRADES_TABLE,
    CREATE_PORTFOLIO_TABLE,
    CREATE_STRATEGY_STATE_TABLE,
]
