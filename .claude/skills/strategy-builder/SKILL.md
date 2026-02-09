---
name: strategy-builder
description: Build trading strategies from natural language descriptions. Guides users through requirements gathering, design, implementation, and verification. Use when the user asks to "create a strategy", "build a strategy", "new strategy", "write a strategy", or describes a trading idea they want implemented.
---

# Strategy Builder

Build trading strategies for the Jesse trading system from natural language descriptions. Guides users through requirements gathering, design, implementation, and verification.

## Workflow

### Phase 1: Gather requirements

Ask the user to describe their trading strategy in plain English. Then:

1. **Clarify terminology first**: Identify any trading jargon, slang, or domain-specific terms in the description (e.g., "orderblock", "deviation", "fair value gap", "liquidity sweep", "breaker block", "CHoCH", "BOS"). Ask the user to define each unfamiliar term precisely — what it looks like on a chart, how to detect it programmatically with candle data, and any parameters involved. Do NOT assume you know what a term means — always confirm with the user.

2. **Accept visual references**: Users can share chart screenshots or annotated diagrams to illustrate concepts. Use these to better understand the strategy's visual logic (e.g., what an orderblock looks like, where a deviation occurs, what the range boundaries are).

3. Ask targeted follow-up questions until the strategy is fully specified. Cover:

- **Entry conditions**: What triggers opening a long or short position? Be specific about indicators, price action, or orderflow signals.
- **Exit conditions**: How are positions closed? Stop loss and take profit levels? Signal-based exits?
- **Timeframes**: Which candle timeframes are needed? (1m, 5m, 15m, 1h, 4h, 1d, 1w)
- **Position sizing**: What percentage of equity per trade? (default: 1%)
- **Indicators/calculations**: What technical indicators are needed? (MA, RSI, Donchian channels, CVD, OI, custom)
- **Position management**: What happens if already in a position? Allow multiple positions? Close opposite before entering?

Do NOT proceed until the strategy is clearly defined. Ask as many questions as needed.

### Phase 2: Design the strategy

Before writing code:

1. Read the reference files to understand the framework:
   - `src/strategy/base.py` — Strategy ABC interface
   - `src/core/types.py` — Signal, Candle, MultiTimeframeData types
   - `src/core/portfolio.py` — Portfolio interface
   - `src/strategy/examples/` — read ALL example strategies for patterns

2. Summarize the strategy specification back to the user:
   - Entry logic (long and short)
   - Exit logic (SL/TP values or formulas)
   - Timeframes declared
   - Required helper functions (indicators)
   - State variables needed
   - Configurable parameters

3. Get user confirmation before implementing.

### Phase 3: Implement

Write the strategy file to `strategies/<snake_case_name>.py`. Follow these patterns:

**Required structure:**
```python
from __future__ import annotations
from typing import Any
from src.core.portfolio import Portfolio
from src.core.types import Candle, MultiTimeframeData, Signal
from src.strategy.base import Strategy

class MyStrategy(Strategy):
    timeframes = ["1m"]  # Declare needed timeframes

    def __init__(self, param1: float = default, ...) -> None:
        # Store configurable parameters
        # Initialize state variables
        pass

    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        # Main logic — called on every candle close
        # Return list of Signal objects (can be empty)
        pass

    def get_state(self) -> dict[str, Any]:
        # Return serializable state for crash recovery
        pass

    def set_state(self, state: dict[str, Any]) -> None:
        # Restore state from dict
        pass
```

**Key APIs:**

```python
# Accessing candle data
data['1m'].latest              # Current candle (Candle object)
data['1m'].latest.close        # Current close price
data['1m'].history             # List of historical candles
data['4h'].latest.open_interest  # Orderflow: open interest
data['1m'].latest.cvd          # Orderflow: cumulative volume delta

# Candle properties
candle.open, candle.high, candle.low, candle.close, candle.volume
candle.is_bullish              # close > open
candle.is_bearish              # close < open
candle.range                   # high - low
candle.body                    # abs(close - open)

# Creating signals
Signal.open_long(size_percent=0.01, stop_loss=95000, take_profit=105000)
Signal.open_short(size_percent=0.01, stop_loss=105000, take_profit=95000)
Signal.close(position_id="...")   # None closes the first open position

# Portfolio access
portfolio.balance              # Current cash balance
portfolio.equity               # Balance + unrealized PnL
portfolio.positions            # List of open Position objects
portfolio.has_position         # True if any open positions
pos.side                       # "long" or "short"
pos.id                         # Position ID for targeted close
pos.entry_price                # Entry price
pos.unrealized_pnl(price)      # Current unrealized PnL
```

**Implementation rules:**
- Return early if insufficient historical data for indicators
- Close opposite positions before opening new ones
- Use configurable parameters via `__init__` (don't hardcode values)
- Implement `get_state()`/`set_state()` if the strategy has any instance state
- All indicator calculations must be helper functions in the same file
- No external dependencies (no numpy, pandas, ta-lib)
- Guard against edge cases: division by zero, None values, empty lists

### Phase 4: Verify

After writing the strategy:

1. Run `ruff check strategies/<file>.py` and `ruff format strategies/<file>.py`
2. Run `mypy strategies/<file>.py`
3. Verify the strategy loads:
   ```bash
   python -c "from src.strategy.loader import load_strategy; s = load_strategy('ClassName'); print(f'Loaded {type(s).__name__} with timeframes {s.timeframes}')"
   ```
4. Tell the user how to backtest:
   ```
   python main.py backtest --strategy ClassName --start 2024-01-01 --end 2024-12-01
   ```

## Guidelines

- Strategies go in `strategies/` (user strategies, not committed to repo).
- Class names are PascalCase. File names are snake_case.
- The `on_candle()` method fires on every close of the lowest declared timeframe. All declared timeframes are delivered simultaneously via `data[timeframe]`.
- For multi-timeframe strategies: use higher timeframes for trend/bias, lower for entries.
- CVD (cumulative volume delta) and open interest are available on candles as `.cvd` and `.open_interest`.
- SL/TP resolution: when both hit in one candle, the engine drills down to lower timeframes to determine which hit first. If ambiguous at 1m, SL is assumed (conservative).
- No hedging — close opposite positions before opening new direction.
- Default risk is 1% of equity (`size_percent=0.01`).
