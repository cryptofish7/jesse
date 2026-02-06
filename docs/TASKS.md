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

- [x] Create `src/core/types.py`
  - [x] Define `Candle` dataclass
    - [x] Fields: timestamp, open, high, low, close, volume, open_interest, cvd
    - [x] Add helper methods (is_bullish, is_bearish, range, body)
  - [x] Define `Signal` dataclass
    - [x] Fields: direction, size_percent, stop_loss, take_profit, position_id
    - [x] Add factory methods: `open_long()`, `open_short()`, `close()`
  - [x] Define `Position` dataclass
    - [x] Fields: id, side, entry_price, entry_time, size, size_usd, stop_loss, take_profit
    - [x] Add `unrealized_pnl()` method
  - [x] Define `Trade` dataclass
    - [x] Fields: id, side, entry_price, exit_price, entry_time, exit_time, size, pnl, pnl_percent, exit_reason
  - [x] Define `TimeframeData` dataclass
    - [x] Fields: latest, history
  - [x] Define `MultiTimeframeData` class (dict wrapper)

- [x] Create `src/core/portfolio.py`
  - [x] Define `Portfolio` class
    - [x] Fields: initial_balance, balance, positions, trades
    - [x] Property: `equity` (balance + unrealized PnL)
    - [x] Property: `has_position`
    - [x] Method: `get_position(id)`
    - [x] Method: `open_position(position)`
    - [x] Method: `close_position(position_id, trade)`

- [x] Write unit tests for core types
  - [x] Test Candle helper methods
  - [x] Test Signal factory methods
  - [x] Test Position unrealized PnL calculation
  - [x] Test Portfolio equity calculation
  - [x] Test Portfolio position management

---

## Milestone 3: Data Layer — Historical

**Goal:** Fetch and cache historical OHLCV data from exchanges.

- [x] Create `src/data/provider.py`
  - [x] Define `DataProvider` ABC
    - [x] Abstract method: `get_historical_candles()`
    - [x] Abstract method: `subscribe()`
    - [x] Abstract method: `unsubscribe()`

- [x] Create `src/data/cache.py`
  - [x] Implement Parquet read function
  - [x] Implement Parquet write function
  - [x] Implement cache path generation (`{symbol}_{timeframe}.parquet`)
  - [x] Implement cache existence check
  - [x] Implement cache date range detection

- [x] Create `src/data/historical.py`
  - [x] Implement `HistoricalDataProvider` class
    - [x] Initialize ccxt exchange client
    - [x] Implement `get_historical_candles()`
      - [x] Check cache first
      - [x] Fetch missing data from exchange
      - [x] Handle pagination (exchange limits)
      - [x] Merge with cached data
      - [x] Save updated cache
    - [x] Support all timeframes (1m, 5m, 15m, 1h, 4h, 1d, 1w)
    - [x] Handle rate limiting with retries

- [x] Create `src/data/orderflow.py`
  - [x] Implement Open Interest fetching
    - [x] Check exchange API for OI endpoint
    - [x] Fetch and align with candle timestamps
  - [x] Implement CVD calculation
    - [x] Check if exchange provides aggregated delta
    - [x] If not, approximate: `cvd += volume * sign(close - open)`
    - [x] Store as cumulative running total

- [ ] Switch default exchange to Binance with required API key authentication
  - [ ] Change default exchange from `bybit` to `binance` in `src/config.py`
  - [ ] Add required `api_key: str` and `api_secret: str` fields to Settings
  - [ ] Update `_create_exchange()` in `src/data/historical.py` to pass credentials to ccxt
  - [ ] Update `.env.example` with `API_KEY` and `API_SECRET` fields
  - [ ] Create `tests/conftest.py` with dummy env vars for test isolation
  - [ ] Update existing tests and add credential pass-through tests

- [x] Write integration tests for data layer
  - [x] Test fetching 1 day of 1m candles
  - [x] Test cache read/write
  - [x] Test cache merge (existing + new data)
  - [x] Test OI data fetching
  - [x] Test CVD calculation

---

## Milestone 4: Strategy Interface

**Goal:** Define the strategy base class and multi-timeframe data delivery.

- [x] Create `src/strategy/base.py`
  - [x] Define `Strategy` ABC
    - [x] Class attribute: `timeframes: list[str]`
    - [x] Abstract method: `on_candle(data, portfolio) -> list[Signal]`
    - [x] Optional method: `on_init(data)`
    - [x] Optional method: `get_state() -> dict` (for persistence)
    - [x] Optional method: `set_state(state: dict)` (for recovery)

- [x] Create `src/core/timeframe.py`
  - [x] Implement `TimeframeAggregator` class
    - [x] Track multiple timeframes simultaneously
    - [x] Align higher timeframe candles to lower timeframe events
    - [x] Build `MultiTimeframeData` on each candle
    - [x] Manage history length (default: 1 year per timeframe)
  - [x] Implement timeframe utilities
    - [x] `get_timeframe_minutes(tf: str) -> int`
    - [x] `get_lower_timeframe(tf: str) -> str | None`
    - [x] `is_timeframe_complete(tf: str, timestamp: datetime) -> bool`

- [x] Create example strategy
  - [x] Create `src/strategy/examples/ma_crossover.py`
    - [x] Simple moving average crossover
    - [x] Configurable parameters (fast_period, slow_period, risk_percent)
    - [x] Demonstrate proper Signal usage

- [x] Write unit tests
  - [x] Test TimeframeAggregator alignment
  - [x] Test MultiTimeframeData construction
  - [x] Test example strategy signal generation

---

## Milestone 5: Backtest Executor

**Goal:** Implement simulated trade execution for backtesting.

- [x] Create `src/execution/executor.py`
  - [x] Define `Executor` ABC
    - [x] Abstract method: `execute(signal, price, portfolio) -> Position | Trade | None`
    - [x] Abstract method: `close_position(position, price, reason) -> Trade`

- [x] Create `src/execution/backtest.py`
  - [x] Implement `BacktestExecutor` class
    - [x] Fill at candle close price
    - [x] Calculate position size from percentage
    - [x] Generate unique position IDs
    - [x] Create Position on open signals
    - [x] Create Trade on close signals

- [x] Create `src/execution/sl_tp.py`
  - [x] Implement `SLTPMonitor` class
    - [x] Method: `check(position, candle) -> Literal['stop_loss', 'take_profit'] | None`
    - [x] Handle long positions (SL below, TP above)
    - [x] Handle short positions (SL above, TP below)
  - [x] Implement drill-down resolution
    - [x] Method: `resolve(position, candle, available_candles) -> Literal['stop_loss', 'take_profit']`
    - [x] Fetch lower timeframe candles when both hit
    - [x] Recursively drill down (4h → 1h → 15m → 5m → 1m)
    - [x] Conservative fallback at 1m (assume SL)

- [x] Write unit tests
  - [x] Test basic SL hit detection
  - [x] Test basic TP hit detection
  - [x] Test drill-down when both hit same candle
  - [x] Test conservative fallback at 1m
  - [x] Test position size calculation
  - [x] Test PnL calculation

---

## Milestone 6: Backtest Engine

**Goal:** Orchestrate backtesting — feed data to strategy, execute signals, track results.

- [x] Create `src/core/engine.py`
  - [x] Implement `Engine` class
    - [x] Constructor: strategy, data_provider, executor, alerter (optional), persist (bool)
    - [x] Method: `run() -> BacktestResults | None`
    - [x] Method: `run_backtest() -> BacktestResults`
    - [x] Method: `run_forward_test()` (placeholder for now)

- [x] Implement backtest loop in `Engine`
  - [x] Load historical data for all declared timeframes
  - [x] Initialize TimeframeAggregator
  - [x] Call `strategy.on_init()` with historical data
  - [x] Iterate through candles chronologically
    - [x] Update TimeframeAggregator
    - [x] Check SL/TP for open positions
    - [x] Call `strategy.on_candle()`
    - [x] Execute returned signals
    - [x] Track equity over time
  - [x] Generate BacktestResults

- [x] Define `BacktestResults` dataclass
  - [x] Fields: trades, equity_curve, start_time, end_time
  - [x] Property: `win_rate`
  - [x] Property: `profit_factor`
  - [x] Property: `total_return`
  - [x] Property: `max_drawdown`
  - [x] Method: `summary() -> str`

- [x] Write integration tests
  - [x] Test full backtest with MA crossover strategy
  - [x] Test multiple positions simultaneously
  - [x] Test SL/TP triggered during backtest
  - [x] Verify equity curve calculation
  - [x] Verify metrics calculation

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
  - [ ] Implement `fetch-data` command with incremental update support
    - [ ] Make `--timeframe` optional (default: `1m` — the engine only needs 1m; others are aggregated)
    - [ ] Make `--start` optional (default: 4 years ago if no cache; last cached timestamp if cache exists)
    - [ ] Make `--end` optional (default: current UTC time)
    - [ ] Wire `cmd_fetch_data` to `HistoricalDataProvider.get_historical_candles()`
      - Already handles: cache check, gap detection, incremental fetch, merge, Parquet write
    - [ ] Log summary on completion: date range, candle count, cache file path
    - [ ] Close exchange connection after fetch (`provider.close()`)
    - [ ] Usage examples:
      - `python main.py fetch-data` — update default symbol (top-up if cache exists, 4yr download if not)
      - `python main.py fetch-data --start 2022-01-01 --end 2026-01-01` — explicit range
      - `python main.py fetch-data --symbol ETH/USDT:USDT` — different symbol
    - [ ] Scheduling: use cron for periodic updates (no built-in scheduler needed)
      - Example: `0 2 1 * * cd /path/to/jesse && .venv/bin/python main.py fetch-data`
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
| 2. Core Types | Complete | 3/3 |
| 3. Data Layer — Historical | In Progress | 5/6 |
| 4. Strategy Interface | Complete | 4/4 |
| 5. Backtest Executor | Complete | 4/4 |
| 6. Backtest Engine | Complete | 4/4 |
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

**Total: 25/61 tasks complete**
