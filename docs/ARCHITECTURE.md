# Architecture Document
## Jesse — BTC/USDT Perpetual Trading System

### Version 1.0 | January 2025

---

## 1. Overview

This document describes the technical architecture for Jesse, the BTC/USDT perpetual futures trading system. It covers system components, data flow, concurrency model, storage strategy, and key design decisions.

**Related Documents:**
- [Product Requirements Document (PRD)](./PRD.md)
- [Development Tasks](./TASKS.md)
- [Development Guide](./CLAUDE.md)

---

## 2. Architecture Principles

| Principle | Description |
|-----------|-------------|
| **Minimal Strategy Interface** | Strategies should be simple to write — receive data, return signals |
| **Unified Codebase** | Same strategy code runs in backtest and forward test modes |
| **Event-Driven** | Engine reacts to candle close events, not polling |
| **Async-First** | Use asyncio for all I/O operations (WebSocket, HTTP, database) |
| **Separation of Concerns** | Clear boundaries between data, execution, strategy, and persistence |
| **Fail-Safe** | Preserve state on errors, recover gracefully on restart |

---

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              TRADING SYSTEM                                 │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                           ASYNC EVENT LOOP                            │  │
│  │                                                                       │  │
│  │  ┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐     │  │
│  │  │    Data     │     │             │     │                     │     │  │
│  │  │   Provider  │────▶│   Engine    │────▶│     Executor        │     │  │
│  │  │             │     │             │     │                     │     │  │
│  │  │ • Historical│     │ • Candle    │     │ • BacktestExecutor  │     │  │
│  │  │ • LiveFeed  │     │   routing   │     │ • PaperExecutor     │     │  │
│  │  │ • Orderflow │     │ • MTF agg   │     │                     │     │  │
│  │  └─────────────┘     │ • SL/TP mon │     └──────────┬──────────┘     │  │
│  │                      │ • Position  │                │                │  │
│  │                      │   mgmt      │                ▼                │  │
│  │                      └──────┬──────┘     ┌─────────────────────┐     │  │
│  │                             │            │   Discord Alerter   │     │  │
│  │                             │            └─────────────────────┘     │  │
│  │                             ▼                                        │  │
│  │                      ┌─────────────┐                                 │  │
│  │                      │  Strategy   │                                 │  │
│  │                      │ (user code) │                                 │  │
│  │                      └─────────────┘                                 │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         STORAGE LAYER                                 │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────┐     ┌─────────────────────────────┐     │  │
│  │  │   Parquet Files         │     │   SQLite Database           │     │  │
│  │  │                         │     │                             │     │  │
│  │  │ • OHLCV candles         │     │ • Open positions            │     │  │
│  │  │ • Open Interest         │     │ • Trade history             │     │  │
│  │  │ • CVD data              │     │ • Portfolio state           │     │  │
│  │  │ • Per symbol/timeframe  │     │ • Strategy state            │     │  │
│  │  └─────────────────────────┘     └─────────────────────────────┘     │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Component Details

### 4.1 Data Provider

**Responsibility:** Fetch and serve market data (historical and live)

**Interface:**
```python
class DataProvider(ABC):
    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> list[Candle]:
        """Fetch historical OHLCV + OI + CVD data."""
        pass
    
    @abstractmethod
    async def subscribe(
        self,
        symbol: str,
        timeframes: list[str],
        callback: Callable[[str, Candle], Awaitable[None]]
    ) -> None:
        """Subscribe to live candle updates."""
        pass
    
    @abstractmethod
    async def unsubscribe(self) -> None:
        """Clean up subscriptions."""
        pass
```

**Implementations:**

| Class | Mode | Description |
|-------|------|-------------|
| `HistoricalDataProvider` | Backtest | Loads from Parquet cache, fetches from exchange if missing |
| `LiveDataProvider` | Forward test | WebSocket connection to exchange |

**Data Sources (in order of preference):**
1. Binance — largest volume, best historical depth (default)
2. Bybit — good perpetual API, provides OI data
3. Hyperliquid — decentralized alternative

**CVD Approach:**
- Check if exchange provides pre-aggregated delta volume per candle
- If not, approximate from candle data: `cvd += volume * sign(close - open)`
- Store CVD as running cumulative total

---

### 4.2 Engine

**Responsibility:** Orchestrate data flow, manage positions, monitor SL/TP

**Key Functions:**
- Receive candles from DataProvider
- Aggregate multi-timeframe data
- Call strategy's `on_candle()` method
- Process signals into orders
- Monitor open positions for SL/TP hits
- Coordinate with Executor for fills

**Interface:**
```python
class Engine:
    def __init__(
        self,
        strategy: Strategy,
        data_provider: DataProvider,
        executor: Executor,
        alerter: object | None = None,
        persist: bool = False,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        self.strategy = strategy
        self.data_provider = data_provider
        self.executor = executor
        self.alerter = alerter
        self.persist = persist
        self.start = start
        self.end = end
        self.portfolio = Portfolio(initial_balance=executor.initial_balance)

    async def run(self) -> BacktestResults | None:
        """Main entry point. Returns results for backtest, runs forever for live."""
        pass

    async def _check_sl_tp(self, candle: Candle) -> None:
        """Check if any positions hit SL or TP."""
        pass
```

**Multi-Timeframe Aggregation:**

When a strategy declares `timeframes = ['1m', '4h']`:
1. Engine subscribes to both timeframes
2. On each 1m candle close, engine provides:
   - Latest 1m candle
   - Current state of 4h candle (updates every 240 1m candles)
   - History for both timeframes
3. Strategy receives `MultiTimeframeData` with both

```python
@dataclass
class TimeframeData:
    latest: Candle
    history: list[Candle]  # Last N candles (default: 1 year worth)

class MultiTimeframeData(dict[str, TimeframeData]):
    """Access via data['1m'], data['4h'], etc."""
    pass
```

---

### 4.3 Strategy

**Responsibility:** Implement trading logic

**Interface:**
```python
class Strategy(ABC):
    timeframes: list[str] = ['1m']  # Override in subclass
    
    def __init__(self, **params):
        """Store configurable parameters."""
        pass
    
    @abstractmethod
    def on_candle(
        self,
        data: MultiTimeframeData,
        portfolio: Portfolio
    ) -> list[Signal]:
        """
        Called on each candle close of the lowest declared timeframe.
        Return list of signals (can be empty).
        """
        pass
    
    def on_init(self, data: MultiTimeframeData) -> None:
        """Optional: called once with historical data before main loop."""
        pass
```

**Signal Types:**
```python
@dataclass
class Signal:
    direction: Literal['long', 'short', 'close']
    size_percent: float | None = None  # % of portfolio (for open)
    stop_loss: float | None = None     # Absolute price (for open)
    take_profit: float | None = None   # Absolute price (for open)
    position_id: str | None = None     # For closing specific position
    
    @classmethod
    def open_long(cls, size_percent: float, stop_loss: float, take_profit: float) -> Signal:
        return cls('long', size_percent, stop_loss, take_profit)
    
    @classmethod
    def open_short(cls, size_percent: float, stop_loss: float, take_profit: float) -> Signal:
        return cls('short', size_percent, stop_loss, take_profit)
    
    @classmethod
    def close(cls, position_id: str | None = None) -> Signal:
        return cls('close', position_id=position_id)
```

---

### 4.4 Executor

**Responsibility:** Execute trades (simulated or paper)

**Interface:**
```python
class Executor(ABC):
    @abstractmethod
    async def execute(
        self,
        signal: Signal,
        current_price: float,
        portfolio: Portfolio
    ) -> Position | Trade | None:
        """
        Execute a signal.
        Returns new Position for opens, Trade for closes, None if rejected.
        """
        pass
    
    @abstractmethod
    async def close_position(
        self,
        position: Position,
        price: float,
        reason: Literal['stop_loss', 'take_profit', 'signal']
    ) -> Trade:
        """Close a position at given price."""
        pass
```

**Implementations:**

| Class | Mode | Behavior |
|-------|------|----------|
| `BacktestExecutor` | Backtest | Fill at candle close price, instant execution |
| `PaperExecutor` | Forward test | Fill at current market price, simulated |

---

### 4.5 SL/TP Monitoring

**Responsibility:** Detect when positions hit stop-loss or take-profit

**Algorithm:**

```
For each open position:
    For each new candle (lowest available timeframe first):
        If position is LONG:
            If candle.low <= stop_loss:
                Mark SL hit at this candle's timestamp
            If candle.high >= take_profit:
                Mark TP hit at this candle's timestamp
        
        If position is SHORT:
            If candle.high >= stop_loss:
                Mark SL hit at this candle's timestamp
            If candle.low <= take_profit:
                Mark TP hit at this candle's timestamp
        
        If both SL and TP hit on same candle:
            Drill down to lower timeframe (see Resolution Algorithm)
        
        Return whichever was hit first (or None if neither)
```

**SL/TP Resolution Algorithm (when both hit in same candle):**

```
TIMEFRAME_ORDER = ['4h', '1h', '15m', '5m', '1m']

function resolve_sl_tp(position, candle, current_timeframe):
    sl_hit = check_sl(position, candle)
    tp_hit = check_tp(position, candle)
    
    if sl_hit AND tp_hit:
        next_tf = get_next_lower_timeframe(current_timeframe)
        
        if next_tf is None:
            # Already at 1m, cannot drill further
            return 'stop_loss'  # Conservative fallback
        
        # Fetch lower timeframe candles for this period
        sub_candles = fetch_candles(next_tf, candle.timestamp, candle.close_timestamp)
        
        for sub_candle in sub_candles:
            result = resolve_sl_tp(position, sub_candle, next_tf)
            if result is not None:
                return result
        
        # Should not reach here, but fallback to conservative
        return 'stop_loss'
    
    elif sl_hit:
        return 'stop_loss'
    elif tp_hit:
        return 'take_profit'
    else:
        return None
```

---

### 4.6 Portfolio Manager

**Responsibility:** Track positions, calculate PnL

```python
@dataclass
class Portfolio:
    initial_balance: float
    balance: float | None = None  # Available USDT (defaults to initial_balance)
    positions: list[Position]
    trades: list[Trade]     # Closed positions
    _current_price: float = 0.0

    def update_price(self, price: float) -> None:
        """Update the last known market price for equity calculation."""
        self._current_price = price

    @property
    def equity(self) -> float:
        """Balance + unrealized PnL of open positions."""
        unrealized = sum(p.unrealized_pnl(self._current_price) for p in self.positions)
        return self.balance + unrealized

    @property
    def has_position(self) -> bool:
        return len(self.positions) > 0

    def get_position(self, position_id: str) -> Position | None:
        return next((p for p in self.positions if p.id == position_id), None)

    def open_position(self, position: Position) -> None:
        self.positions.append(position)
        self.balance -= position.size_usd  # Lock margin

    def close_position(self, position_id: str, trade: Trade) -> None:
        self.positions = [p for p in self.positions if p.id != position_id]
        self.trades.append(trade)
        self.balance += trade.size_usd + trade.pnl  # Return margin + PnL
```

---

### 4.7 Alerter

**Responsibility:** Send notifications via Discord

```python
class DiscordAlerter:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient()
    
    async def send_alert(self, message: str, embed: dict | None = None) -> None:
        payload = {"content": message}
        if embed:
            payload["embeds"] = [embed]
        await self.client.post(self.webhook_url, json=payload)
    
    async def on_strategy_start(self, strategy_name: str) -> None:
        await self.send_alert(f"🚀 Strategy **{strategy_name}** is now active")
    
    async def on_trade_open(self, position: Position) -> None:
        await self.send_alert(
            f"📈 **{position.side.upper()}** opened\n"
            f"Entry: ${position.entry_price:,.2f}\n"
            f"Size: {position.size} BTC (${position.size_usd:,.2f})\n"
            f"SL: ${position.stop_loss:,.2f} | TP: ${position.take_profit:,.2f}"
        )
    
    async def on_trade_close(self, trade: Trade) -> None:
        emoji = "✅" if trade.pnl > 0 else "❌"
        await self.send_alert(
            f"{emoji} **{trade.side.upper()}** closed ({trade.exit_reason})\n"
            f"Entry: ${trade.entry_price:,.2f} → Exit: ${trade.exit_price:,.2f}\n"
            f"PnL: ${trade.pnl:,.2f} ({trade.pnl_percent:+.2f}%)"
        )
```

---

### 4.8 Persistence Layer

**Responsibility:** Store and recover state

**Storage Strategy:**

| Data Type | Storage | Format | Reason |
|-----------|---------|--------|--------|
| OHLCV candles | Parquet | `data/candles/{symbol}_{timeframe}.parquet` | Fast columnar reads |
| Open Interest | Parquet | Same file as candles | Co-located with price data |
| CVD | Parquet | Same file as candles | Co-located with price data |
| Open positions | SQLite | `data/trading.db` | Relational, transactional |
| Trade history | SQLite | `data/trading.db` | Queryable |
| Portfolio state | SQLite | `data/trading.db` | ACID compliance |

**SQLite Schema:**

```sql
-- Positions table (open positions)
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    side TEXT NOT NULL,  -- 'long' or 'short'
    entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL,  -- ISO timestamp
    size REAL NOT NULL,  -- BTC
    size_usd REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    created_at TEXT NOT NULL
);

-- Trades table (closed positions)
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    exit_price REAL NOT NULL,
    exit_time TEXT NOT NULL,
    size REAL NOT NULL,
    size_usd REAL NOT NULL,
    pnl REAL NOT NULL,
    pnl_percent REAL NOT NULL,
    exit_reason TEXT NOT NULL,  -- 'stop_loss', 'take_profit', 'signal'
    created_at TEXT NOT NULL
);

-- Portfolio state
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton
    initial_balance REAL NOT NULL,
    balance REAL NOT NULL,
    updated_at TEXT NOT NULL
);

-- Strategy state (for crash recovery)
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_name TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,  -- Serialized strategy state
    updated_at TEXT NOT NULL
);
```

**Parquet Schema:**

```python
# Each parquet file contains:
{
    'timestamp': datetime64[ns],  # Candle open time
    'open': float64,
    'high': float64,
    'low': float64,
    'close': float64,
    'volume': float64,
    'open_interest': float64,
    'cvd': float64,  # Cumulative volume delta
}
```

---

## 5. Data Flow

### 5.1 Backtest Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            BACKTEST FLOW                                    │
│                                                                             │
│  1. Load historical data                                                    │
│     ┌─────────────┐     ┌─────────────┐                                    │
│     │   Parquet   │────▶│  Historical │                                    │
│     │   Cache     │     │  Provider   │                                    │
│     └─────────────┘     └──────┬──────┘                                    │
│                                │                                            │
│  2. Initialize strategy        │                                            │
│                                ▼                                            │
│                         ┌─────────────┐                                    │
│                         │   Engine    │                                    │
│                         └──────┬──────┘                                    │
│                                │                                            │
│  3. Iterate through candles    │                                            │
│     ┌──────────────────────────┼──────────────────────────┐                │
│     │                          ▼                          │                │
│     │  For each candle:  ┌─────────────┐                  │                │
│     │                    │  Strategy   │                  │                │
│     │                    │ on_candle() │                  │                │
│     │                    └──────┬──────┘                  │                │
│     │                           │                         │                │
│     │                           ▼                         │                │
│     │                    ┌─────────────┐                  │                │
│     │                    │  Backtest   │                  │                │
│     │                    │  Executor   │                  │                │
│     │                    └──────┬──────┘                  │                │
│     │                           │                         │                │
│     │                           ▼                         │                │
│     │                    ┌─────────────┐                  │                │
│     │                    │  Check      │                  │                │
│     │                    │  SL/TP      │                  │                │
│     │                    └─────────────┘                  │                │
│     └─────────────────────────────────────────────────────┘                │
│                                                                             │
│  4. Generate results                                                        │
│                         ┌─────────────┐                                    │
│                         │  Analysis   │                                    │
│                         │  & Charts   │                                    │
│                         └─────────────┘                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Forward Test Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FORWARD TEST FLOW                                  │
│                                                                             │
│  1. Startup & Recovery                                                      │
│     ┌─────────────┐     ┌─────────────┐                                    │
│     │   SQLite    │────▶│   Engine    │                                    │
│     │   (state)   │     │  (restore)  │                                    │
│     └─────────────┘     └──────┬──────┘                                    │
│                                │                                            │
│  2. Connect to exchange        │                                            │
│                                ▼                                            │
│                         ┌─────────────┐                                    │
│                         │    Live     │                                    │
│                         │  Provider   │◀──── WebSocket                     │
│                         └──────┬──────┘                                    │
│                                │                                            │
│  3. Event loop (runs forever)  │                                            │
│     ┌──────────────────────────┼──────────────────────────┐                │
│     │                          ▼                          │                │
│     │  On candle:        ┌─────────────┐                  │                │
│     │                    │  Strategy   │                  │                │
│     │                    │ on_candle() │                  │                │
│     │                    └──────┬──────┘                  │                │
│     │                           │                         │                │
│     │                           ▼                         │                │
│     │                    ┌─────────────┐                  │                │
│     │                    │   Paper     │                  │                │
│     │                    │  Executor   │                  │                │
│     │                    └──────┬──────┘                  │                │
│     │                           │                         │                │
│     │              ┌────────────┼────────────┐            │                │
│     │              ▼            ▼            ▼            │                │
│     │       ┌──────────┐ ┌──────────┐ ┌──────────┐       │                │
│     │       │  SQLite  │ │  Check   │ │ Discord  │       │                │
│     │       │ (persist)│ │  SL/TP   │ │ (alert)  │       │                │
│     │       └──────────┘ └──────────┘ └──────────┘       │                │
│     └─────────────────────────────────────────────────────┘                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Concurrency Model

### 6.1 Async Architecture

The system uses Python's `asyncio` for all I/O operations:

```python
async def main():
    # All components are async-aware
    engine = Engine(
        strategy=MyStrategy(),
        data_provider=LiveDataProvider(),
        executor=PaperExecutor(),
        alerter=DiscordAlerter(webhook_url="...")
    )
    
    await engine.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### 6.2 Task Structure (Forward Test)

```
Main Event Loop
│
├── WebSocket Handler (LiveDataProvider)
│   └── On message → parse candle → callback to Engine
│
├── Engine._on_candle()
│   ├── Update MTF data structures
│   ├── Check SL/TP for open positions
│   ├── Call strategy.on_candle()
│   ├── Execute signals
│   └── Persist state
│
└── Periodic Tasks
    ├── Heartbeat / connection health check
    └── State backup (every N minutes)
```

### 6.3 Backtest Optimization

For backtesting, async overhead is unnecessary since there's no I/O waiting. The backtest runs synchronously in a tight loop:

```python
async def run_backtest(self) -> BacktestResults:
    # Load all data upfront
    candles = await self.data_provider.get_historical_candles(...)
    
    # Synchronous iteration (fast)
    for candle in candles:
        self._process_candle(candle)  # No await needed
    
    return self._generate_results()
```

---

## 7. Error Handling

### 7.1 Error Categories

| Category | Examples | Action |
|----------|----------|--------|
| **Transient** | Network timeout, rate limit, WebSocket disconnect | Auto-retry with exponential backoff |
| **Recoverable** | Invalid API response, parse error | Log, retry once, alert if persists |
| **Critical** | Auth failure, invalid config, database corruption | Alert immediately, stop |
| **Unknown** | Unhandled exception | Alert, preserve state, stop |

### 7.2 Retry Strategy

```python
async def with_retry(
    func: Callable,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0
) -> Any:
    for attempt in range(max_attempts):
        try:
            return await func()
        except TransientError as e:
            if attempt == max_attempts - 1:
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            await asyncio.sleep(delay)
    
    raise MaxRetriesExceeded()
```

### 7.3 Graceful Shutdown

```python
async def run(self):
    try:
        await self._main_loop()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except CriticalError as e:
        await self.alerter.send_alert(f"🚨 Critical error: {e}")
    finally:
        await self._persist_state()
        await self._cleanup()
```

---

## 8. Configuration

### 8.1 Environment Variables

```bash
# Exchange settings
EXCHANGE=binance                  # bybit, binance, hyperliquid
API_KEY=your_api_key_here         # Required: exchange API key
API_SECRET=your_api_secret_here   # Required: exchange API secret
SYMBOL=BTC/USDT:USDT             # Perpetual symbol
INITIAL_BALANCE=10000            # Starting paper balance (USDT)

# Alerts
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Paths
DATABASE_PATH=data/trading.db
CACHE_PATH=data/candles/
OUTPUT_PATH=output/

# Logging
LOG_LEVEL=INFO
```

### 8.2 Config Schema (Pydantic v2)

```python
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    exchange: Literal["bybit", "binance", "hyperliquid"] = "binance"
    symbol: str = "BTC/USDT:USDT"
    api_key: str = ""
    api_secret: str = ""
    initial_balance: float = 10000.0

    discord_webhook_url: str | None = None

    database_path: str = "data/trading.db"
    cache_path: str = "data/candles/"
    output_path: str = "output/"

    log_level: str = "INFO"

    # History defaults
    default_history_candles: int = 525600  # ~1 year of 1m candles
```

---

## 9. File Structure

```
jesse/
├── CLAUDE.md -> docs/CLAUDE.md  # Symlink
├── src/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── types.py           # Candle, Signal, Position, Trade, Portfolio
│   │   ├── engine.py          # Main engine orchestration
│   │   ├── portfolio.py       # Position tracking, PnL calculation
│   │   └── timeframe.py       # Multi-timeframe aggregation logic
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── provider.py        # DataProvider ABC
│   │   ├── historical.py      # HistoricalDataProvider (Parquet + API)
│   │   ├── live.py            # LiveDataProvider (WebSocket)
│   │   ├── orderflow.py       # OI and CVD fetching/calculation
│   │   └── cache.py           # Parquet read/write utilities
│   │
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── executor.py        # Executor ABC
│   │   ├── backtest.py        # BacktestExecutor
│   │   ├── paper.py           # PaperExecutor
│   │   └── sl_tp.py           # SL/TP monitoring and resolution
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py            # Strategy ABC
│   │   └── examples/
│   │       ├── __init__.py
│   │       └── ma_crossover.py
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── metrics.py         # Win rate, profit factor, etc.
│   │   └── charts.py          # Equity curve, trade markers (Plotly)
│   │
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── discord.py         # Discord webhook alerter
│   │
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── database.py        # SQLite operations
│   │   └── models.py          # Raw SQL schema definitions
│   │
│   └── config.py              # Pydantic settings
│
├── strategies/                 # User strategies (outside src/)
│   └── my_strategy.py
│
├── data/                       # Runtime data (gitignored)
│   ├── candles/               # Parquet cache
│   └── trading.db             # SQLite database
│
├── output/                     # Generated charts/reports (gitignored)
│
├── tests/
│   ├── __init__.py
│   ├── test_engine.py
│   ├── test_portfolio.py
│   ├── test_sl_tp.py
│   └── ...
│
├── docs/
│   ├── CLAUDE.md              # Development guide
│   ├── PRD.md                 # Product requirements
│   ├── ARCHITECTURE.md        # This file
│   └── TASKS.md               # Development tasks
│
├── main.py                     # Entry point
├── pyproject.toml             # Dependencies
├── .env.example               # Example environment config
└── .gitignore
```

---

## 10. Dependencies

```toml
[project]
name = "jesse"
version = "1.0.0"
requires-python = ">=3.11"

dependencies = [
    # Core
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    
    # Data
    "ccxt>=4.0",              # Exchange API
    "pyarrow>=14.0",          # Parquet support
    "pandas>=2.0",            # Data manipulation
    "websockets>=12.0",       # WebSocket client
    
    # Database
    "aiosqlite>=0.19",        # Async SQLite
    
    # HTTP
    "httpx>=0.25",            # Async HTTP client
    
    # Visualization
    "plotly>=5.18",           # Interactive charts
    
    # Utilities
    "python-dotenv>=1.0",     # .env loading
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",        # Coverage
    "ruff>=0.1",              # Linting
    "mypy>=1.7",              # Type checking
]
```

---

## 11. Deployment (Railway)

### 11.1 Railway Configuration

```toml
# railway.toml
[build]
builder = "nixpacks"

[deploy]
restartPolicyType = "always"
restartPolicyMaxRetries = 3
```

### 11.2 Procfile

```
worker: python main.py forward-test
```

### 11.3 Persistent Storage

Railway provides persistent volumes. Mount at `/data` and configure:

```bash
DATABASE_PATH=/data/trading.db
CACHE_PATH=/data/candles/
```

### 11.4 Environment Variables

Set in Railway dashboard:
- `EXCHANGE`
- `API_KEY`
- `API_SECRET`
- `SYMBOL`
- `INITIAL_BALANCE`
- `DISCORD_WEBHOOK_URL`
- `LOG_LEVEL`

---

## 12. Testing Strategy

### 12.1 Unit Tests

| Component | Test Focus |
|-----------|------------|
| `Portfolio` | Position opening/closing, PnL calculation |
| `SL/TP Monitor` | Detection logic, drill-down resolution |
| `Timeframe Aggregator` | MTF alignment, history management |
| `Metrics` | Win rate, profit factor calculations |

### 12.2 Integration Tests

| Test | Description |
|------|-------------|
| Backtest E2E | Run sample strategy, verify results |
| Data fetching | Fetch from exchange, cache to Parquet |
| State recovery | Simulate crash, verify position restoration |

### 12.3 Test Commands

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src

# Run specific test file
pytest tests/test_sl_tp.py
```

---

## 13. Open Technical Decisions

| Decision | Options | Status |
|----------|---------|--------|
| Exchange selection | Bybit vs Binance vs Hyperliquid | **Decided: Binance** (best historical depth for 1-4yr goal) |
| CVD data source | Exchange API vs approximation | To investigate API availability |
| WebSocket library | `websockets` vs `aiohttp` | To decide based on exchange SDK |

---

## 14. Glossary

See `PRD.md` Section 8 for term definitions.
