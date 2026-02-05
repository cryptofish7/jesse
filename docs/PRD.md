# Product Requirements Document
## Jesse — BTC/USDT Perpetual Trading System

### Version 1.0 | January 2025

---

## 1. Overview

### 1.1 Purpose

Jesse is a Python-based trading system for backtesting and forward testing perpetual futures strategies on BTC/USDT. Designed for rapid strategy iteration with a clean, minimal interface for strategy development.

### 1.2 Goals

- Backtest price action and orderflow strategies against 1-4 years of historical data
- Forward test (paper trade) strategies in real-time with crash recovery
- Support multi-timeframe analysis (1m to 1w)
- Make adding new strategies as simple as possible
- Provide clear performance metrics (win rate, profit factor) with visual output

### 1.3 Non-Goals (for v1)

- Live trading with real money
- Order book data
- Machine learning integration
- Hedging / simultaneous long and short
- Trailing stops
- Trading fees simulation
- Automatic parameter optimization

---

## 2. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| U1 | Trader | Write a strategy in minimal code | I can quickly test new ideas |
| U2 | Trader | Backtest on multiple timeframes simultaneously | I can build strategies like "4h context, 1m entry" |
| U3 | Trader | See win rate and profit factor after backtest | I can evaluate strategy performance |
| U4 | Trader | View equity curve and trade markers on chart | I can visually inspect strategy behavior |
| U5 | Trader | Run paper trading for days continuously | I can validate strategies in live conditions |
| U6 | Trader | Get Discord alerts when trades trigger | I stay informed without watching terminal |
| U7 | Trader | Resume forward test after system crash | I don't lose position state |
| U8 | Trader | Easily change strategy parameters between runs | I can find optimal settings |

> **Note:** For system architecture, technical specifications, deployment configuration, and example usage, see [`ARCHITECTURE.md`](./ARCHITECTURE.md) and [`CLAUDE.md`](./CLAUDE.md).

---

## 3. Functional Requirements

### 3.1 Data Provider

| ID | Requirement | Priority |
|----|-------------|----------|
| D1 | Fetch OHLCV data from Binance, Bybit, or Hyperliquid (whichever has easiest API) | Must |
| D2 | Support timeframes: 1m, 5m, 15m, 1h, 4h, 1d, 1w | Must |
| D3 | Fetch at least 1 year of historical data, ideally 4 years | Must |
| D4 | Fetch Open Interest data per candle | Must |
| D5 | Calculate CVD (cumulative volume delta) from trade data | Must |
| D6 | Cache historical data locally to avoid repeated API calls | Must |
| D7 | Stream live candles via WebSocket for forward testing | Must |
| D8 | Support additional trading pairs beyond BTC/USDT in future | Should |

### 3.2 Engine

| ID | Requirement | Priority |
|----|-------------|----------|
| E1 | Feed candles to strategy on each candle close | Must |
| E2 | Provide all declared timeframes to strategy simultaneously | Must |
| E3 | Automatically align and aggregate multi-timeframe data | Must |
| E4 | Monitor open positions for SL/TP hits | Must |
| E5 | Execute SL/TP at specified price levels | Must |
| E6 | Pass portfolio state to strategy on each candle | Must |
| E7 | Support both backtest and forward test modes with same strategy code | Must |

### 3.3 Strategy Interface

| ID | Requirement | Priority |
|----|-------------|----------|
| S1 | Minimal interface: strategy receives candles + portfolio, returns signals | Must |
| S2 | Strategy declares required timeframes upfront | Must |
| S3 | Strategy can access historical candles for all declared timeframes | Must |
| S4 | Strategy can access OI and CVD data | Must |
| S5 | Strategy can open multiple independent positions | Must |
| S6 | Strategy specifies SL/TP as fixed price levels per position | Must |
| S7 | Strategy specifies position size as % of portfolio | Must |
| S8 | Strategies support configurable parameters via constructor | Must |
| S9 | Optional `on_init()` hook for warming up indicators | Should |

**Example strategy interface:**

```python
class MyStrategy(Strategy):
    timeframes = ['1m', '4h']  # Declare what you need

    def __init__(self, orderblock_lookback: int = 20, risk_percent: float = 1.0):
        self.orderblock_lookback = orderblock_lookback
        self.risk_percent = risk_percent

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        candle_1m = data['1m'].latest
        candle_4h = data['4h'].latest
        oi = data['1m'].open_interest
        cvd = data['1m'].cvd

        # Strategy logic here...

        return [
            Signal.open_long(
                size_percent=self.risk_percent,
                stop_loss=95000,
                take_profit=105000
            )
        ]
```

### 3.4 Position Management

| ID | Requirement | Priority |
|----|-------------|----------|
| P1 | Track multiple independent positions | Must |
| P2 | Each position has its own entry price, size, SL, TP | Must |
| P3 | Positions close independently when their SL or TP is hit | Must |
| P4 | Size positions as percentage of current portfolio value | Must |
| P5 | Track realized and unrealized PnL | Must |
| P6 | No hedging (long and short simultaneously) | Must |

### 3.5 Execution

| ID | Requirement | Priority |
|----|-------------|----------|
| X1 | Backtest: fill orders at candle close price | Must |
| X2 | Backtest: check SL/TP against candle high/low | Must |
| X3 | Paper trading: simulate fills at current market price | Must |
| X4 | No trading fees simulation | Must |

### 3.6 Analysis & Output

| ID | Requirement | Priority |
|----|-------------|----------|
| A1 | Calculate win rate | Must |
| A2 | Calculate profit factor | Must |
| A3 | Generate equity curve chart | Must |
| A4 | Generate price chart with trade entry/exit markers | Must |
| A5 | Export trade log (entry time, exit time, PnL, duration) | Should |
| A6 | Calculate total return | Should |
| A7 | Calculate max drawdown | Should |

### 3.7 Alerts

| ID | Requirement | Priority |
|----|-------------|----------|
| AL1 | Send Discord webhook when strategy becomes active | Must |
| AL2 | Send Discord webhook when trade is opened | Must |
| AL3 | Send Discord webhook when trade is closed (SL/TP/signal) | Must |
| AL4 | Include relevant details: price, size, PnL | Must |

### 3.8 State Persistence

| ID | Requirement | Priority |
|----|-------------|----------|
| ST1 | Persist open positions to SQLite | Must |
| ST2 | Persist portfolio state (balance, equity) | Must |
| ST3 | On startup, restore open positions from database | Must |
| ST4 | Cache historical candle data locally | Must |

---

## 4. Data Structures

### 4.1 Candle

```python
@dataclass
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float
    cvd: float  # Cumulative volume delta (running total)
```

### 4.2 Signal

```python
@dataclass
class Signal:
    direction: Literal['long', 'short', 'close']
    size_percent: float  # % of portfolio
    stop_loss: float     # Absolute price
    take_profit: float   # Absolute price
    position_id: str | None = None  # For closing specific position
```

### 4.3 Position

```python
@dataclass
class Position:
    id: str
    side: Literal['long', 'short']
    entry_price: float
    entry_time: datetime
    size: float  # In base currency (BTC)
    size_usd: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
```

### 4.4 Trade (closed position)

```python
@dataclass
class Trade:
    id: str
    side: Literal['long', 'short']
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    size: float
    pnl: float
    pnl_percent: float
    exit_reason: Literal['stop_loss', 'take_profit', 'signal']
```

### 4.5 Portfolio

```python
@dataclass
class Portfolio:
    balance: float  # Available USDT
    equity: float   # Balance + unrealized PnL
    positions: list[Position]

    def has_position(self) -> bool: ...
    def get_position(self, id: str) -> Position | None: ...
```

### 4.6 MultiTimeframeData

```python
@dataclass
class TimeframeData:
    latest: Candle
    history: list[Candle]  # Most recent N candles
    open_interest: float   # Latest OI
    cvd: float             # Cumulative volume delta

class MultiTimeframeData(dict[str, TimeframeData]):
    """Access via data['1m'], data['4h'], etc."""
    pass
```

---

## 5. Success Criteria

| Criteria | Target |
|----------|--------|
| New strategy can be written in <50 lines of code | Yes |
| Backtest 1 year of 1m data completes in <60 seconds | Yes |
| Forward test runs continuously for 7+ days without intervention | Yes |
| System recovers open positions after crash/restart | Yes |
| Win rate and profit factor calculated correctly | Yes |

---

## 6. Future Enhancements (out of scope for v1)

- Live trading execution
- Additional assets beyond BTC/USDT
- Order book data
- ML-based strategies
- Automatic parameter optimization (grid search)
- Web dashboard for monitoring
- Trailing stops
- Hedging support
- Trading fees simulation

---

## 7. Open Questions

| Question | Status |
|----------|--------|
| Which exchange has easiest OI/CVD data access? | To investigate during implementation |
| How far back can we get 1m candle data? | To verify with exchange APIs |
| Historical trade data availability for CVD calculation | To verify with exchange APIs |

---

## 8. Glossary

| Term | Definition |
|------|------------|
| BOS | Break of Structure — price breaking a previous swing high/low |
| CVD | Cumulative Volume Delta — running sum of (buy volume - sell volume), indicates buying/selling pressure |
| MTF | Multi-timeframe — using multiple candle intervals simultaneously |
| OI | Open Interest — total number of outstanding derivative contracts |
| Orderblock | Price action concept — area where institutional orders are believed to exist |
| Parquet | Columnar file format optimized for analytical queries |
| Profit Factor | Gross profit / gross loss — above 1.0 is profitable |
| SL | Stop Loss — price level to exit at a loss |
| TP | Take Profit — price level to exit at a profit |
| Win Rate | Percentage of trades that were profitable |
