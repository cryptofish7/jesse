# TASKS.md
## Jesse — Development Tasks

Track progress by marking tasks as complete: `- [x]`

---

## Milestone 1: Project Setup

**Goal:** Establish project foundation with proper structure, dependencies, and configuration.

- [x] Initialize project structure
  - [x] Create directory structure (`src/`, `strategies/`, `data/`, `output/`, `tests/`, `docs/`)
  - [x] Create `__init__.py` files for all packages
  - [x] Create `.gitignore` (ignore `data/`, `output/`, `.env`, `__pycache__/`, `.venv/`)

- [x] Set up dependencies
  - [x] Create `pyproject.toml` with all dependencies
  - [x] Create `requirements.txt` for Railway deployment
  - [x] Set up virtual environment
  - [x] Verify all packages install correctly

- [x] Set up configuration
  - [x] Create `src/config.py` with Pydantic settings
  - [x] Create `.env.example` template
  - [x] Support environment variable overrides
  - [x] Add configuration validation

- [x] Set up logging
  - [x] Configure structured logging
  - [x] Add log levels (DEBUG, INFO, WARNING, ERROR)
  - [x] Add file and console handlers

- [x] Create entry point
  - [x] Create `main.py` with CLI argument parsing
  - [x] Add `backtest` command placeholder
  - [x] Add `forward-test` command placeholder

---

## Milestone 2: Core Types

**Goal:** Define all data structures used throughout the system.

- [ ] Create `src/core/types.py`
  - [ ] Define `Candle` dataclass
    - [ ] Fields: timestamp, open, high, low, close, volume, open_interest, cvd
    - [ ] Add helper methods (is_bullish, is_bearish, range, body)
  - [ ] Define `Signal` dataclass
    - [ ] Fields: direction, size_percent, stop_loss, take_profit, position_id
    - [ ] Add factory methods: `open_long()`, `open_short()`, `close()`
  - [ ] Define `Position` dataclass
    - [ ] Fields: id, side, entry_price, entry_time, size, size_usd, stop_loss, take_profit
    - [ ] Add `unrealized_pnl()` method
  - [ ] Define `Trade` dataclass
    - [ ] Fields: id, side, entry_price, exit_price, entry_time, exit_time, size, pnl, pnl_percent, exit_reason
  - [ ] Define `TimeframeData` dataclass
    - [ ] Fields: latest, history
  - [ ] Define `MultiTimeframeData` class (dict wrapper)

- [ ] Create `src/core/portfolio.py`
  - [ ] Define `Portfolio` class
    - [ ] Fields: initial_balance, balance, positions, trades
    - [ ] Property: `equity` (balance + unrealized PnL)
    - [ ] Property: `has_position`
    - [ ] Method: `get_position(id)`
    - [ ] Method: `open_position(position)`
    - [ ] Method: `close_position(position_id, trade)`

- [ ] Write unit tests for core types
  - [ ] Test Candle helper methods
  - [ ] Test Signal factory methods
  - [ ] Test Position unrealized PnL calculation
  - [ ] Test Portfolio equity calculation
  - [ ] Test Portfolio position management

---

## Milestone 3: Data Layer — Historical

**Goal:** Fetch and cache historical OHLCV data from exchanges.

- [ ] Create `src/data/provider.py`
  - [ ] Define `DataProvider` ABC
    - [ ] Abstract method: `get_historical_candles()`
    - [ ] Abstract method: `subscribe()`
    - [ ] Abstract method: `unsubscribe()`

- [ ] Create `src/data/cache.py`
  - [ ] Implement Parquet read function
  - [ ] Implement Parquet write function
  - [ ] Implement cache path generation (`{symbol}_{timeframe}.parquet`)
  - [ ] Implement cache existence check
  - [ ] Implement cache date range detection

- [ ] Create `src/data/historical.py`
  - [ ] Implement `HistoricalDataProvider` class
    - [ ] Initialize ccxt exchange client
    - [ ] Implement `get_historical_candles()`
      - [ ] Check cache first
      - [ ] Fetch missing data from exchange
      - [ ] Handle pagination (exchange limits)
      - [ ] Merge with cached data
      - [ ] Save updated cache
    - [ ] Support all timeframes (1m, 5m, 15m, 1h, 4h, 1d, 1w)
    - [ ] Handle rate limiting with retries

- [ ] Create `src/data/orderflow.py`
  - [ ] Implement Open Interest fetching
    - [ ] Check exchange API for OI endpoint
    - [ ] Fetch and align with candle timestamps
  - [ ] Implement CVD calculation
    - [ ] Check if exchange provides aggregated delta
    - [ ] If not, approximate: `cvd += volume * sign(close - open)`
    - [ ] Store as cumulative running total

- [ ] Write integration tests for data layer
  - [ ] Test fetching 1 day of 1m candles
  - [ ] Test cache read/write
  - [ ] Test cache merge (existing + new data)
  - [ ] Test OI data fetching
  - [ ] Test CVD calculation

---

## Milestone 4: Strategy Interface

**Goal:** Define the strategy base class and multi-timeframe data delivery.

- [ ] Create `src/strategy/base.py`
  - [ ] Define `Strategy` ABC
    - [ ] Class attribute: `timeframes: list[str]`
    - [ ] Abstract method: `on_candle(data, portfolio) -> list[Signal]`
    - [ ] Optional method: `on_init(data)`
    - [ ] Optional method: `get_state() -> dict` (for persistence)
    - [ ] Optional method: `set_state(state: dict)` (for recovery)

- [ ] Create `src/core/timeframe.py`
  - [ ] Implement `TimeframeAggregator` class
    - [ ] Track multiple timeframes simultaneously
    - [ ] Align higher timeframe candles to lower timeframe events
    - [ ] Build `MultiTimeframeData` on each candle
    - [ ] Manage history length (default: 1 year per timeframe)
  - [ ] Implement timeframe utilities
    - [ ] `get_timeframe_minutes(tf: str) -> int`
    - [ ] `get_lower_timeframe(tf: str) -> str | None`
    - [ ] `is_timeframe_complete(tf: str, timestamp: datetime) -> bool`

- [ ] Create example strategy
  - [ ] Create `src/strategy/examples/ma_crossover.py`
    - [ ] Simple moving average crossover
    - [ ] Configurable parameters (fast_period, slow_period, risk_percent)
    - [ ] Demonstrate proper Signal usage

- [ ] Write unit tests
  - [ ] Test TimeframeAggregator alignment
  - [ ] Test MultiTimeframeData construction
  - [ ] Test example strategy signal generation

---

## Milestone 5: Backtest Executor

**Goal:** Implement simulated trade execution for backtesting.

- [ ] Create `src/execution/executor.py`
  - [ ] Define `Executor` ABC
    - [ ] Abstract method: `execute(signal, price, portfolio) -> Position | Trade | None`
    - [ ] Abstract method: `close_position(position, price, reason) -> Trade`

- [ ] Create `src/execution/backtest.py`
  - [ ] Implement `BacktestExecutor` class
    - [ ] Fill at candle close price
    - [ ] Calculate position size from percentage
    - [ ] Generate unique position IDs
    - [ ] Create Position on open signals
    - [ ] Create Trade on close signals

- [ ] Create `src/execution/sl_tp.py`
  - [ ] Implement `SLTPMonitor` class
    - [ ] Method: `check(position, candle) -> Literal['stop_loss', 'take_profit'] | None`
    - [ ] Handle long positions (SL below, TP above)
    - [ ] Handle short positions (SL above, TP below)
  - [ ] Implement drill-down resolution
    - [ ] Method: `resolve(position, candle, available_candles) -> Literal['stop_loss', 'take_profit']`
    - [ ] Fetch lower timeframe candles when both hit
    - [ ] Recursively drill down (4h → 1h → 15m → 5m → 1m)
    - [ ] Conservative fallback at 1m (assume SL)

- [ ] Write unit tests
  - [ ] Test basic SL hit detection
  - [ ] Test basic TP hit detection
  - [ ] Test drill-down when both hit same candle
  - [ ] Test conservative fallback at 1m
  - [ ] Test position size calculation
  - [ ] Test PnL calculation

---

## Milestone 6: Backtest Engine

**Goal:** Orchestrate backtesting — feed data to strategy, execute signals, track results.

- [ ] Create `src/core/engine.py`
  - [ ] Implement `Engine` class
    - [ ] Constructor: strategy, data_provider, executor, alerter (optional), persist (bool)
    - [ ] Method: `run() -> BacktestResults | None`
    - [ ] Method: `run_backtest() -> BacktestResults`
    - [ ] Method: `run_forward_test()` (placeholder for now)

- [ ] Implement backtest loop in `Engine`
  - [ ] Load historical data for all declared timeframes
  - [ ] Initialize TimeframeAggregator
  - [ ] Call `strategy.on_init()` with historical data
  - [ ] Iterate through candles chronologically
    - [ ] Update TimeframeAggregator
    - [ ] Check SL/TP for open positions
    - [ ] Call `strategy.on_candle()`
    - [ ] Execute returned signals
    - [ ] Track equity over time
  - [ ] Generate BacktestResults

- [ ] Define `BacktestResults` dataclass
  - [ ] Fields: trades, equity_curve, start_time, end_time
  - [ ] Property: `win_rate`
  - [ ] Property: `profit_factor`
  - [ ] Property: `total_return`
  - [ ] Property: `max_drawdown`
  - [ ] Method: `summary() -> str`

- [ ] Write integration tests
  - [ ] Test full backtest with MA crossover strategy
  - [ ] Test multiple positions simultaneously
  - [ ] Test SL/TP triggered during backtest
  - [ ] Verify equity curve calculation
  - [ ] Verify metrics calculation

---

## Milestone 7: Analysis & Visualization

**Goal:** Calculate performance metrics and generate charts.

- [ ] Create `src/analysis/metrics.py`
  - [ ] Implement `calculate_win_rate(trades) -> float`
  - [ ] Implement `calculate_profit_factor(trades) -> float`
  - [ ] Implement `calculate_total_return(initial, final) -> float`
  - [ ] Implement `calculate_max_drawdown(equity_curve) -> float`
  - [ ] Implement `calculate_sharpe_ratio(equity_curve) -> float` (optional)

- [ ] Create `src/analysis/charts.py`
  - [ ] Implement `plot_equity_curve(equity_curve, output_path)`
    - [ ] Use Plotly for interactive HTML
    - [ ] Show equity over time
    - [ ] Mark drawdown periods
  - [ ] Implement `plot_trades(candles, trades, output_path)`
    - [ ] Price chart with candlesticks
    - [ ] Entry markers (green for long, red for short)
    - [ ] Exit markers (with SL/TP/signal distinction)
    - [ ] Optional: show SL/TP levels as horizontal lines

- [ ] Add chart generation to BacktestResults
  - [ ] Method: `plot_equity_curve(output_path)`
  - [ ] Method: `plot_trades(output_path)`
  - [ ] Method: `export_trades(output_path)` (CSV)

- [ ] Write unit tests
  - [ ] Test win rate calculation (edge cases: 0 trades, all wins, all losses)
  - [ ] Test profit factor calculation (edge case: no losses)
  - [ ] Test max drawdown calculation
  - [ ] Test chart generation (verify files created)

---

## Milestone 8: Persistence Layer

**Goal:** Save and restore state for crash recovery.

- [ ] Create `src/persistence/models.py`
  - [ ] Define SQLite schema
    - [ ] `positions` table
    - [ ] `trades` table
    - [ ] `portfolio` table
    - [ ] `strategy_state` table

- [ ] Create `src/persistence/database.py`
  - [ ] Implement `Database` class
    - [ ] Method: `initialize()` — create tables if not exist
    - [ ] Method: `save_position(position)`
    - [ ] Method: `delete_position(position_id)`
    - [ ] Method: `get_open_positions() -> list[Position]`
    - [ ] Method: `save_trade(trade)`
    - [ ] Method: `get_trades() -> list[Trade]`
    - [ ] Method: `save_portfolio(portfolio)`
    - [ ] Method: `get_portfolio() -> Portfolio | None`
    - [ ] Method: `save_strategy_state(name, state_dict)`
    - [ ] Method: `get_strategy_state(name) -> dict | None`
  - [ ] Use aiosqlite for async operations
  - [ ] Implement transaction support

- [ ] Integrate persistence with Engine
  - [ ] On startup: restore positions, portfolio, strategy state
  - [ ] On position open: save position
  - [ ] On position close: delete position, save trade
  - [ ] Periodic: save portfolio state
  - [ ] On shutdown: save all state

- [ ] Write unit tests
  - [ ] Test position save/load roundtrip
  - [ ] Test trade save/load roundtrip
  - [ ] Test portfolio save/load roundtrip
  - [ ] Test strategy state save/load roundtrip
  - [ ] Test recovery after simulated crash

---

## Milestone 9: Live Data Provider

**Goal:** Stream real-time candle data via WebSocket.

- [ ] Create `src/data/live.py`
  - [ ] Implement `LiveDataProvider` class
    - [ ] Initialize WebSocket connection
    - [ ] Method: `subscribe(symbol, timeframes, callback)`
      - [ ] Subscribe to candle streams for all timeframes
      - [ ] Parse incoming messages
      - [ ] Convert to Candle objects
      - [ ] Call callback on candle close
    - [ ] Method: `unsubscribe()`
      - [ ] Close WebSocket connection
      - [ ] Clean up resources
    - [ ] Handle connection errors
      - [ ] Auto-reconnect with exponential backoff
      - [ ] Alert after N failed attempts

- [ ] Implement exchange-specific WebSocket handlers
  - [ ] Bybit kline WebSocket
  - [ ] (Optional) Binance kline WebSocket
  - [ ] (Optional) Hyperliquid WebSocket

- [ ] Handle live OI and CVD
  - [ ] Subscribe to OI updates if available
  - [ ] Calculate CVD from trade stream or approximate

- [ ] Write integration tests
  - [ ] Test WebSocket connection
  - [ ] Test candle parsing
  - [ ] Test reconnection after disconnect
  - [ ] Test multiple timeframe subscription

---

## Milestone 10: Paper Executor

**Goal:** Simulate order execution for forward testing.

- [ ] Create `src/execution/paper.py`
  - [ ] Implement `PaperExecutor` class
    - [ ] Fill at current market price
    - [ ] Track simulated positions
    - [ ] Calculate PnL in real-time
    - [ ] Method: `execute(signal, price, portfolio)`
    - [ ] Method: `close_position(position, price, reason)`

- [ ] Add real-time position monitoring
  - [ ] Update unrealized PnL on each price update
  - [ ] Check SL/TP on each tick (not just candle close)
  - [ ] Trigger alerts on position changes

- [ ] Write unit tests
  - [ ] Test paper execution fills
  - [ ] Test real-time PnL updates
  - [ ] Test SL/TP monitoring

---

## Milestone 11: Discord Alerts

**Goal:** Send notifications for trade events.

- [ ] Create `src/alerts/discord.py`
  - [ ] Implement `DiscordAlerter` class
    - [ ] Constructor: webhook_url
    - [ ] Method: `send_alert(message, embed)`
    - [ ] Method: `on_strategy_start(strategy_name)`
    - [ ] Method: `on_trade_open(position)`
    - [ ] Method: `on_trade_close(trade)`
    - [ ] Method: `on_error(error_message)`
  - [ ] Format messages with embeds (colors, fields)
  - [ ] Handle rate limiting
  - [ ] Handle send failures gracefully

- [ ] Integrate alerts with Engine
  - [ ] Alert on forward test start
  - [ ] Alert on position open
  - [ ] Alert on position close (SL/TP/signal)
  - [ ] Alert on errors

- [ ] Write unit tests
  - [ ] Test message formatting
  - [ ] Mock webhook calls
  - [ ] Test rate limit handling

---

## Milestone 12: Forward Test Engine

**Goal:** Run strategies in real-time with paper trading.

- [ ] Extend `Engine` for forward testing
  - [ ] Implement `run_forward_test()` method
    - [ ] Connect to LiveDataProvider
    - [ ] Restore state from database
    - [ ] Send startup alert
    - [ ] Enter main event loop
  - [ ] Handle graceful shutdown
    - [ ] Catch SIGINT/SIGTERM
    - [ ] Save all state
    - [ ] Close connections
    - [ ] Send shutdown alert

- [ ] Implement crash recovery
  - [ ] On startup: check for existing positions
  - [ ] Restore portfolio state
  - [ ] Restore strategy state
  - [ ] Resume monitoring open positions

- [ ] Add health monitoring
  - [ ] Track last candle timestamp
  - [ ] Alert if no data received for N minutes
  - [ ] Periodic heartbeat log

- [ ] Write integration tests
  - [ ] Test forward test startup
  - [ ] Test state recovery after restart
  - [ ] Test graceful shutdown

---

## Milestone 13: CLI & Entry Point

**Goal:** Finalize command-line interface for running the system.

- [ ] Update `main.py`
  - [ ] Implement `backtest` command
    - [ ] Arguments: --strategy, --start, --end, --initial-balance
    - [ ] Load strategy by name
    - [ ] Run backtest
    - [ ] Print results summary
    - [ ] Generate charts
  - [ ] Implement `forward-test` command
    - [ ] Arguments: --strategy, --initial-balance
    - [ ] Load strategy by name
    - [ ] Run forward test (blocking)
  - [ ] Implement `fetch-data` command (utility)
    - [ ] Arguments: --symbol, --timeframe, --start, --end
    - [ ] Fetch and cache historical data
  - [ ] Add `--help` for all commands

- [ ] Add strategy discovery
  - [ ] Scan `strategies/` directory
  - [ ] Import strategy classes by name
  - [ ] Validate strategy implements required interface

- [ ] Write CLI tests
  - [ ] Test argument parsing
  - [ ] Test strategy loading
  - [ ] Test error handling for invalid inputs

---

## Milestone 14: Deployment

**Goal:** Deploy forward testing to Railway.

- [ ] Create Railway configuration
  - [ ] Create `railway.toml`
  - [ ] Create `Procfile`
  - [ ] Configure build settings

- [ ] Set up persistent storage
  - [ ] Create volume in Railway dashboard
  - [ ] Configure mount path (`/data`)
  - [ ] Update config to use volume paths

- [ ] Configure environment variables
  - [ ] Set exchange credentials (if needed)
  - [ ] Set Discord webhook URL
  - [ ] Set initial balance
  - [ ] Set log level

- [ ] Test deployment
  - [ ] Deploy to Railway
  - [ ] Verify WebSocket connection
  - [ ] Verify Discord alerts
  - [ ] Verify state persistence across restarts
  - [ ] Monitor for 24 hours

- [ ] Document deployment process
  - [ ] Update README with deployment instructions
  - [ ] Document environment variables
  - [ ] Document volume requirements

---

## Milestone 15: Documentation & Polish

**Goal:** Finalize documentation and improve code quality.

- [ ] Write README.md
  - [ ] Project overview
  - [ ] Quick start guide
  - [ ] Strategy development guide
  - [ ] Configuration reference
  - [ ] Deployment guide

- [ ] Add code documentation
  - [ ] Docstrings for all public classes/methods
  - [ ] Type hints throughout
  - [ ] Inline comments for complex logic

- [ ] Improve test coverage
  - [ ] Aim for >80% coverage
  - [ ] Add edge case tests
  - [ ] Add integration tests

- [ ] Code quality
  - [ ] Run ruff linter, fix all issues
  - [ ] Consistent code style
  - [ ] Remove dead code
  - [ ] Optimize hot paths (backtest loop)

- [ ] Create additional example strategies
  - [ ] RSI overbought/oversold strategy
  - [ ] Breakout strategy
  - [ ] Multi-timeframe example (4h + 1m)

---

## Milestone 16: Future Enhancements (Post-v1)

**Goal:** Track ideas for future development.

See `PRD.md` Section 6 for the full list of post-v1 enhancements.

---

## Progress Summary

| Milestone | Status | Tasks |
|-----------|--------|-------|
| 1. Project Setup | Complete | 5/5 |
| 2. Core Types | Not Started | 0/3 |
| 3. Data Layer — Historical | Not Started | 0/5 |
| 4. Strategy Interface | Not Started | 0/4 |
| 5. Backtest Executor | Not Started | 0/4 |
| 6. Backtest Engine | Not Started | 0/4 |
| 7. Analysis & Visualization | Not Started | 0/4 |
| 8. Persistence Layer | Not Started | 0/4 |
| 9. Live Data Provider | Not Started | 0/4 |
| 10. Paper Executor | Not Started | 0/3 |
| 11. Discord Alerts | Not Started | 0/3 |
| 12. Forward Test Engine | Not Started | 0/4 |
| 13. CLI & Entry Point | Not Started | 0/4 |
| 14. Deployment | Not Started | 0/5 |
| 15. Documentation & Polish | Not Started | 0/5 |
| 16. Future Enhancements | Backlog | — |

**Total: 5/61 tasks complete**
