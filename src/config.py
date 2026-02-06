"""Application configuration loaded from environment variables and .env file."""

from __future__ import annotations

import logging
import sys
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Jesse trading system configuration.

    Values are loaded from environment variables with fallback to .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Exchange settings
    exchange: Literal["bybit", "binance", "hyperliquid"] = "binance"
    symbol: str = "BTC/USDT:USDT"
    api_key: str = ""
    api_secret: str = ""
    initial_balance: float = 10000.0

    # Alerts
    discord_webhook_url: str | None = None

    # Paths
    database_path: str = "data/trading.db"
    cache_path: str = "data/candles/"
    output_path: str = "output/"

    # Logging
    log_level: str = "INFO"

    # History defaults
    default_history_candles: int = 525600  # ~1 year of 1m candles

    @field_validator("initial_balance")
    @classmethod
    def validate_initial_balance(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("initial_balance must be positive")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        v = v.upper()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}, got '{v}'")
        return v


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with console and file handlers.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level))

    # Clear existing handlers to avoid duplicates on re-init
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level))
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root_logger.addHandler(console_handler)

    # File handler — writes to data/jesse.log, graceful fallback if data/ missing
    try:
        file_handler = logging.FileHandler("data/jesse.log")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format, date_format))
        root_logger.addHandler(file_handler)
    except OSError:
        pass


# Module-level singleton
settings = Settings()
