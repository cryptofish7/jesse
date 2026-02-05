# Jesse

BTC/USDT perpetual futures backtesting and forward testing system. Write strategies in minimal Python, test them against historical data, then paper trade in real-time with Discord alerts and crash recovery.

## Features

- **Backtest** against 1-4 years of historical 1m candle data
- **Paper trade** in real-time with automatic state persistence and crash recovery
- **Multi-timeframe** strategies (1m, 5m, 15m, 1h, 4h, 1d, 1w)
- **Orderflow data** — Open Interest and Cumulative Volume Delta per candle
- **Discord alerts** on trade open/close events
- **Performance metrics** — win rate, profit factor, equity curve, trade charts

## Quick Start

```bash
# Clone and install
git clone git@github.com:cryptofish7/jesse.git
cd jesse
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your settings
```

## Write a Strategy

```python
# strategies/my_strategy.py
from src.strategy.base import Strategy
from src.core.types import Signal, MultiTimeframeData, Portfolio

class MyStrategy(Strategy):
    timeframes = ['1m', '4h']

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        candle_4h = data['4h'].latest
        candle_1m = data['1m'].latest

        # Your logic here
        return []
```

## Run a Backtest

```python
from src.core.engine import Engine
from src.data.historical import HistoricalDataProvider
from src.execution.backtest import BacktestExecutor
from strategies.my_strategy import MyStrategy

engine = Engine(
    strategy=MyStrategy(),
    data_provider=HistoricalDataProvider(symbol="BTC/USDT:USDT", start="2024-01-01", end="2024-12-01"),
    executor=BacktestExecutor(initial_balance=10000)
)
results = engine.run()
```

## Run Paper Trading

```python
from src.core.engine import Engine
from src.data.live import LiveDataProvider
from src.execution.paper import PaperExecutor
from src.alerts.discord import DiscordAlerter
from strategies.my_strategy import MyStrategy

engine = Engine(
    strategy=MyStrategy(),
    data_provider=LiveDataProvider(symbol="BTC/USDT:USDT"),
    executor=PaperExecutor(initial_balance=10000),
    alerter=DiscordAlerter(webhook_url="..."),
    persist=True
)
engine.run()  # Runs continuously
```

## Project Structure

```
jesse/
├── src/
│   ├── core/          # Engine, portfolio, types, timeframe aggregation
│   ├── data/          # Historical and live data providers, orderflow
│   ├── execution/     # Backtest and paper executors, SL/TP monitoring
│   ├── strategy/      # Strategy base class and examples
│   ├── analysis/      # Metrics and chart generation
│   ├── alerts/        # Discord webhook alerts
│   └── persistence/   # SQLite state persistence
├── strategies/        # Your strategies go here
├── tests/
└── docs/
    ├── PRD.md         # Product requirements
    ├── ARCHITECTURE.md # System design and technical details
    └── TASKS.md       # Development progress
```

## Configuration

Copy `.env.example` to `.env` and set:

| Variable | Description | Default |
|----------|-------------|---------|
| `EXCHANGE` | Exchange to use (bybit, binance) | `bybit` |
| `SYMBOL` | Trading pair | `BTC/USDT:USDT` |
| `INITIAL_BALANCE` | Starting paper balance (USDT) | `10000` |
| `DISCORD_WEBHOOK_URL` | Discord alerts webhook | — |
| `DATABASE_PATH` | SQLite database path | `data/trading.db` |
| `CACHE_PATH` | Parquet cache directory | `data/candles/` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Development

```bash
pytest                      # Run tests
pytest --cov=src            # With coverage
mypy src/                   # Type checking
```

## Docs

- [Product Requirements](docs/PRD.md) — What the system does
- [Architecture](docs/ARCHITECTURE.md) — How it's built
- [Tasks](docs/TASKS.md) — Development progress
