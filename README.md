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

## Strategy Development

Strategies inherit from `Strategy` and implement a single method: `on_candle()`. The engine calls this on every 1-minute candle close, passing all declared timeframes simultaneously.

### Minimal Example

```python
# strategies/my_strategy.py
from src.strategy.base import Strategy
from src.core.types import Signal, MultiTimeframeData
from src.core.portfolio import Portfolio

class MyStrategy(Strategy):
    timeframes = ['1m']

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        price = data['1m'].latest.close
        history = data['1m'].history  # list of completed Candle objects

        # Return signals or an empty list
        return []
```

### Signals

Strategies communicate with the engine through `Signal` objects:

```python
# Open a long position (100% of equity, with SL and TP)
Signal.open_long(size_percent=1.0, stop_loss=95000, take_profit=105000)

# Open a short position
Signal.open_short(size_percent=1.0, stop_loss=105000, take_profit=95000)

# Close a specific position
Signal.close(position_id="abc123")

# Close the first open position
Signal.close()
```

Every open signal requires `size_percent`, `stop_loss`, and `take_profit`. The engine rejects signals with missing fields.

### Multi-Timeframe Strategies

Declare the timeframes you need. Higher timeframes are aggregated automatically from 1-minute data:

```python
class MyMTFStrategy(Strategy):
    timeframes = ['1m', '4h']

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        trend = data['4h'].latest.close    # Current (in-progress) 4h candle
        history_4h = data['4h'].history    # Completed 4h candles
        entry = data['1m'].latest.close    # Current 1m candle
        return []
```

### State Persistence

For crash recovery during forward testing, implement `get_state()` and `set_state()`:

```python
def get_state(self) -> dict[str, Any]:
    return {"prev_ma": self._prev_ma}

def set_state(self, state: dict[str, Any]) -> None:
    self._prev_ma = state.get("prev_ma")
```

### Data Access

Each timeframe in `data` provides:
- `data['1m'].latest` -- the current candle (Candle object)
- `data['1m'].history` -- list of completed candles
- `data['1m'].latest.cvd` -- cumulative volume delta
- `data['1m'].latest.open_interest` -- open interest

### Example Strategies

Four built-in examples are included in `src/strategy/examples/`:

| Strategy | File | Description |
|----------|------|-------------|
| `MACrossover` | `ma_crossover.py` | Moving average crossover (fast/slow SMA) |
| `RSIStrategy` | `rsi_strategy.py` | RSI overbought/oversold mean-reversion |
| `BreakoutStrategy` | `breakout_strategy.py` | Donchian channel breakout |
| `MTFStrategy` | `mtf_strategy.py` | Multi-timeframe trend-following (4h + 1m) |

Run any example with the CLI:

```bash
python main.py backtest --strategy MACrossover --start 2024-01-01 --end 2024-12-01
python main.py backtest --strategy RSIStrategy --start 2024-01-01 --end 2024-12-01
python main.py backtest --strategy BreakoutStrategy --start 2024-01-01 --end 2024-12-01
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
| `EXCHANGE` | Exchange to use (bybit, binance) | `binance` |
| `API_KEY` | Exchange API key (required) | — |
| `API_SECRET` | Exchange API secret (required) | — |
| `SYMBOL` | Trading pair | `BTC/USDT:USDT` |
| `INITIAL_BALANCE` | Starting paper balance (USDT) | `10000` |
| `DISCORD_WEBHOOK_URL` | Discord alerts webhook | — |
| `DATABASE_PATH` | SQLite database path | `data/trading.db` |
| `CACHE_PATH` | Parquet cache directory | `data/candles/` |
| `LOG_LEVEL` | Logging level | `INFO` |

## CLI Usage

```bash
# Fetch historical data (incremental if cache exists)
python main.py fetch-data

# Fetch with explicit date range
python main.py fetch-data --start 2022-01-01 --end 2026-01-01

# Run a backtest
python main.py backtest --strategy MACrossover --start 2024-01-01 --end 2024-12-01

# Run forward testing (paper trading, runs continuously)
python main.py forward-test --strategy MACrossover
```

Backtest output includes a results summary, equity curve chart (HTML), and trades CSV in `output/<strategy>/`.

### Running Programmatically

```python
from datetime import datetime, UTC
from src.core.engine import Engine
from src.data.historical import HistoricalDataProvider
from src.execution.backtest import BacktestExecutor
from src.strategy.examples.ma_crossover import MACrossover

engine = Engine(
    strategy=MACrossover(),
    data_provider=HistoricalDataProvider(symbol="BTC/USDT:USDT"),
    executor=BacktestExecutor(initial_balance=10000),
    start=datetime(2024, 1, 1, tzinfo=UTC),
    end=datetime(2024, 12, 1, tzinfo=UTC),
)
results = await engine.run()
print(results.summary())
```

For forward testing (paper trading with live data):

```python
from src.core.engine import Engine
from src.data.live import LiveDataProvider
from src.execution.paper import PaperExecutor
from src.alerts.discord import DiscordAlerter

engine = Engine(
    strategy=MACrossover(),
    data_provider=LiveDataProvider(symbol="BTC/USDT:USDT"),
    executor=PaperExecutor(initial_balance=10000),
    alerter=DiscordAlerter(webhook_url="https://discord.com/api/webhooks/..."),
    persist=True,
)
await engine.run()  # Runs continuously until Ctrl+C
```

## Deploy to Railway

Jesse is designed to run as a worker service on [Railway](https://railway.app) for continuous forward testing.

### 1. Create a Railway project

- Link your GitHub repository in the Railway dashboard.
- Railway auto-detects `railway.toml` and `Procfile`.

### 2. Add a persistent volume

Mount a volume at `/data` in the Railway service settings. This stores the SQLite database and Parquet cache across restarts and redeploys.

### 3. Set environment variables

Set these in the Railway dashboard under your service's **Variables** tab:

| Variable | Required | Description |
|----------|----------|-------------|
| `EXCHANGE` | No | Exchange name (`binance`, `bybit`, `hyperliquid`). Default: `binance` |
| `API_KEY` | Yes | Exchange API key for market data |
| `API_SECRET` | Yes | Exchange API secret |
| `SYMBOL` | No | Trading pair. Default: `BTC/USDT:USDT` |
| `INITIAL_BALANCE` | No | Starting paper balance in USDT. Default: `10000` |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook for trade alerts |
| `DATABASE_PATH` | Yes | Set to `/data/trading.db` (volume mount) |
| `CACHE_PATH` | Yes | Set to `/data/candles/` (volume mount) |
| `OUTPUT_PATH` | No | Set to `/data/output/` if needed |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default: `INFO` |

### 4. Deploy

Push to your linked branch. Railway builds and deploys automatically. The `Procfile` starts the forward test worker:

```
worker: python main.py forward-test --strategy MACrossover
```

To use a different strategy, update the `Procfile` or override the start command in Railway settings.

### 5. Verify

After deployment, check:

- **Railway logs**: Confirm the worker starts and connects to the exchange WebSocket.
- **Discord**: Look for the strategy startup alert (if webhook is configured).
- **Restart test**: Restart the service in Railway and verify state is recovered from the volume.

### Changing the strategy

Edit the `Procfile` to point to a different strategy class name:

```
worker: python main.py forward-test --strategy YourStrategy
```

The strategy class must exist in the `strategies/` directory.

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
