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

    # Verify --duration flag is advertised in forward-test help
    "$PYTHON" main.py forward-test --help | grep -q -- '--duration'
    echo "  PASS: forward-test --help includes --duration flag"

    "$PYTHON" main.py fetch-data --help > /dev/null
    echo "  PASS: main.py fetch-data --help"
}

stage_5_import_smoke() {
    echo "--- Stage 5: Import smoke ---"

    "$PYTHON" -c "
from src.config import Settings, settings, parse_duration
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
from src.execution.paper import PaperExecutor
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
from src.persistence.database import Database
from src.persistence.models import SCHEMA_VERSION, ALL_TABLES
"
    echo "  PASS: All key modules import cleanly"
}

stage_6_duration_feature() {
    echo "--- Stage 6: Forward test duration feature ---"

    # parse_duration: valid inputs
    "$PYTHON" -c "
from src.config import parse_duration
assert parse_duration('30m') == 1800, 'Expected 1800 for 30m'
assert parse_duration('48h') == 172800, 'Expected 172800 for 48h'
assert parse_duration('7d') == 604800, 'Expected 604800 for 7d'
"
    echo "  PASS: parse_duration() valid inputs"

    # parse_duration: invalid inputs raise ValueError
    "$PYTHON" -c "
from src.config import parse_duration
import sys
failures = ['', 'abc', '30', '30x', '-5m']
for bad in failures:
    try:
        parse_duration(bad)
        print(f'FAIL: parse_duration({bad!r}) should have raised ValueError')
        sys.exit(1)
    except ValueError:
        pass
"
    echo "  PASS: parse_duration() rejects invalid inputs"

    # FORWARD_TEST_DURATION env var is respected by Settings
    "$PYTHON" -c "
import os
os.environ['FORWARD_TEST_DURATION'] = '24h'
# Re-import to pick up env override
from pydantic_settings import BaseSettings
from src.config import Settings
s = Settings()
assert s.forward_test_duration == '24h', f'Expected 24h, got {s.forward_test_duration}'
"
    echo "  PASS: FORWARD_TEST_DURATION env var configures Settings"
}

stage_7_credentials() {
    echo "--- Stage 7: Credentials ---"

    # Source .env if it exists
    if [ -f .env ]; then
        set -a
        source .env
        set +a
    fi

    # Check if credentials are set and not placeholders
    if [ -z "${API_KEY:-}" ] || [ "$API_KEY" = "your-api-key-here" ] || \
       [ -z "${API_SECRET:-}" ] || [ "$API_SECRET" = "your-api-secret-here" ]; then
        echo "  API credentials required for local deploy."
        echo ""
        read -rp "  API_KEY: " API_KEY
        read -rsp "  API_SECRET: " API_SECRET
        echo ""

        if [ -z "$API_KEY" ] || [ -z "$API_SECRET" ]; then
            echo "  FAIL: Credentials cannot be empty"
            exit 1
        fi

        # Persist to .env for future runs
        if [ -f .env ]; then
            # Update existing .env
            "$PYTHON" -c "
import re, sys
env = open('.env').read()
env = re.sub(r'^API_KEY=.*$', f'API_KEY={sys.argv[1]}', env, flags=re.MULTILINE)
env = re.sub(r'^API_SECRET=.*$', f'API_SECRET={sys.argv[2]}', env, flags=re.MULTILINE)
open('.env', 'w').write(env)
" "$API_KEY" "$API_SECRET"
        else
            # Create .env from template
            cp .env.example .env
            "$PYTHON" -c "
import re, sys
env = open('.env').read()
env = re.sub(r'^API_KEY=.*$', f'API_KEY={sys.argv[1]}', env, flags=re.MULTILINE)
env = re.sub(r'^API_SECRET=.*$', f'API_SECRET={sys.argv[2]}', env, flags=re.MULTILINE)
open('.env', 'w').write(env)
" "$API_KEY" "$API_SECRET"
        fi
        echo "  Credentials saved to .env"
    fi

    export API_KEY
    export API_SECRET
    echo "  PASS: API credentials configured"
}

stage_8_fetch_data() {
    echo "--- Stage 8: Fetch data ---"

    "$PYTHON" main.py fetch-data --start 2025-01-01 --end 2025-01-08
    echo "  PASS: fetch-data"
}

stage_9_backtest() {
    echo "--- Stage 9: Backtest ---"

    "$PYTHON" main.py backtest --strategy MACrossover --start 2025-01-01 --end 2025-01-08

    # Verify output files were created
    STRATEGY_DIR="output/macrossover"
    if [ ! -f "$STRATEGY_DIR/equity_curve.html" ]; then
        echo "  FAIL: equity_curve.html not created"
        exit 1
    fi
    if [ ! -f "$STRATEGY_DIR/trades.csv" ]; then
        echo "  FAIL: trades.csv not created"
        exit 1
    fi

    echo "  PASS: backtest"
}

# --- Run all stages ---
stage_1_environment
stage_2_static_analysis
stage_3_tests
stage_4_cli_smoke
stage_5_import_smoke
stage_6_duration_feature
stage_7_credentials
stage_8_fetch_data
stage_9_backtest

echo ""
echo "DEPLOY OK"
