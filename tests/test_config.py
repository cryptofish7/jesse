"""Tests for configuration and CLI entry point."""

import subprocess
import sys

import pytest

from src.config import Settings, setup_logging


class TestSettings:
    """Test Pydantic Settings configuration."""

    def test_defaults(self):
        s = Settings(_env_file=None)
        assert s.exchange == "bybit"
        assert s.symbol == "BTC/USDT:USDT"
        assert s.initial_balance == 10000.0
        assert s.log_level == "INFO"
        assert s.database_path == "data/trading.db"
        assert s.cache_path == "data/candles/"
        assert s.output_path == "output/"
        assert s.discord_webhook_url is None
        assert s.default_history_candles == 525600

    def test_exchange_rejects_invalid(self):
        with pytest.raises(Exception):
            Settings(exchange="kraken", _env_file=None)

    def test_exchange_accepts_valid(self):
        for ex in ("bybit", "binance", "hyperliquid"):
            s = Settings(exchange=ex, _env_file=None)
            assert s.exchange == ex

    def test_initial_balance_must_be_positive(self):
        with pytest.raises(Exception):
            Settings(initial_balance=0, _env_file=None)
        with pytest.raises(Exception):
            Settings(initial_balance=-100, _env_file=None)

    def test_log_level_normalized_to_uppercase(self):
        s = Settings(log_level="debug", _env_file=None)
        assert s.log_level == "DEBUG"

    def test_log_level_rejects_invalid(self):
        with pytest.raises(Exception):
            Settings(log_level="TRACE", _env_file=None)


class TestSetupLogging:
    """Test logging configuration."""

    def test_setup_logging_creates_handlers(self):
        import logging

        setup_logging("INFO")
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) >= 1  # At least console handler


class TestCLI:
    """Test CLI argument parsing."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "main.py", *args],
            capture_output=True,
            text=True,
        )

    def test_no_command_exits_with_error(self):
        result = self._run()
        assert result.returncode == 1

    def test_help_exits_cleanly(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "backtest" in result.stdout
        assert "forward-test" in result.stdout
        assert "fetch-data" in result.stdout

    def test_backtest_requires_strategy(self):
        result = self._run("backtest", "--start", "2024-01-01", "--end", "2024-06-01")
        assert result.returncode != 0

    def test_backtest_placeholder(self):
        result = self._run(
            "backtest", "--strategy", "TestStrat",
            "--start", "2024-01-01", "--end", "2024-06-01",
        )
        assert result.returncode == 0
        assert "Not yet implemented" in result.stdout

    def test_forward_test_placeholder(self):
        result = self._run("forward-test", "--strategy", "TestStrat")
        assert result.returncode == 0
        assert "Not yet implemented" in result.stdout

    def test_fetch_data_placeholder(self):
        result = self._run(
            "fetch-data", "--timeframe", "1m",
            "--start", "2024-01-01", "--end", "2024-06-01",
        )
        assert result.returncode == 0
        assert "Not yet implemented" in result.stdout
