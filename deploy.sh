#!/usr/bin/env bash
set -euo pipefail

# Jesse — Local smoke test
# Verifies the project runs correctly. Fails fast on first error.

PYTHON="${PYTHON:-python3}"

stage_1_environment() {
    echo "--- Stage 1: Environment ---"

    # Python version >= 3.11
    "$PYTHON" -c "
import sys
v = sys.version_info
assert (v.major, v.minor) >= (3, 11), f'Python >= 3.11 required, got {v.major}.{v.minor}'
"
    echo "  PASS: Python >= 3.11"

    # Key packages importable
    "$PYTHON" -c "import pydantic, pydantic_settings, ccxt, pyarrow, pandas, httpx, plotly"
    echo "  PASS: Core dependencies importable"
}

stage_2_static_analysis() {
    echo "--- Stage 2: Static analysis ---"

    ruff check src/ tests/ main.py
    echo "  PASS: ruff check"

    ruff format --check src/ tests/ main.py
    echo "  PASS: ruff format"

    mypy src/
    echo "  PASS: mypy"
}

stage_3_tests() {
    echo "--- Stage 3: Tests ---"

    pytest -x -q
    echo "  PASS: pytest"
}

stage_4_cli_smoke() {
    echo "--- Stage 4: CLI smoke ---"

    "$PYTHON" main.py --help > /dev/null
    echo "  PASS: main.py --help"

    "$PYTHON" main.py backtest --help > /dev/null
    echo "  PASS: main.py backtest --help"

    "$PYTHON" main.py forward-test --help > /dev/null
    echo "  PASS: main.py forward-test --help"

    "$PYTHON" main.py fetch-data --help > /dev/null
    echo "  PASS: main.py fetch-data --help"
}

stage_5_import_smoke() {
    echo "--- Stage 5: Import smoke ---"

    "$PYTHON" -c "
from src.config import Settings, settings
from src.core.types import Candle, Signal, Position, Trade
from src.core.portfolio import Portfolio
from src.core.timeframe import TimeframeAggregator
from src.core.engine import Engine, BacktestResults, EquityPoint
from src.data.provider import DataProvider
from src.data.historical import HistoricalDataProvider
from src.data.cache import read_candles, write_candles
from src.data.orderflow import approximate_cvd, enrich_with_oi
from src.execution.executor import Executor
from src.execution.backtest import BacktestExecutor
from src.execution.sl_tp import SLTPMonitor
from src.strategy.base import Strategy
from src.strategy.examples.ma_crossover import MACrossover
from src.analysis.metrics import (
    calculate_win_rate,
    calculate_profit_factor,
    calculate_total_return,
    calculate_max_drawdown,
    calculate_sharpe_ratio,
)
from src.analysis.charts import plot_equity_curve, plot_trades
"
    echo "  PASS: All key modules import cleanly"
}

# --- Run all stages ---
stage_1_environment
stage_2_static_analysis
stage_3_tests
stage_4_cli_smoke
stage_5_import_smoke

echo ""
echo "DEPLOY OK"
