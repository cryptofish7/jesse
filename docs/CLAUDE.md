# CLAUDE.md
## Jesse — Development Guide

This file provides context for Claude Code sessions working on this project.

---

## Workflow

### Starting a Session

1. Read project documentation for context (e.g., PRD, architecture docs, README).
2. Check the task tracker (e.g., `docs/TASKS.md`, GitHub Issues) for current progress. Identify the next incomplete task.
3. Start from a clean state on the default branch:
   ```bash
   git checkout main && git pull origin main
   ```

### During Development

- Update the task tracker when tasks are completed or discovered.
- When stuck or going in circles, stop. Re-plan before continuing.
- **On any error:** Spawn the `debugger` subagent with the error context. Use its analysis to fix the issue before continuing.

### After Completing a Task — Autonomous Pipeline

Run this pipeline after every completed task. No user input required unless a step fails and cannot be auto-resolved.

**Step 1: Verify locally.**
Run the project's linting, formatting, type checking, and test commands. Check the Commands section of this file or `pyproject.toml`/`package.json`/`Makefile` for the exact commands. Fix any failures before proceeding.

**Step 2: Consolidate documentation.**
Run the `/docs-consolidator` skill to audit and sync project docs. Skip if the skill is unavailable.

**Step 3: Audit CI/CD pipeline.**
Run the `/ci-cd-pipeline` skill to ensure the GitHub Actions pipeline matches the project's current state. Skip if the skill is unavailable.

**Step 4: Commit all changes.**
Stage and commit everything from the task and from Steps 2-3. Write a concise, descriptive commit message. Use conventional commit prefixes when appropriate (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`, `refactor:`, `test:`).

**Step 5: Push to a new branch and open a PR.**
- Create a branch with a descriptive name: `<type>/<short-slug>` (e.g., `feat/core-types`, `fix/timestamp-bug`, `chore/update-deps`).
- Push and open a PR:
  ```bash
  git checkout -b <branch-name>
  git push -u origin <branch-name>
  gh pr create --fill
  ```

**Step 6: Code review.**
Spawn the `code-reviewer` subagent to review the PR. If the reviewer identifies issues, fix them on the same branch, commit, and push before proceeding.

**Step 7: Wait for CI checks to pass.**
```bash
gh pr checks --watch --fail-fast
```
- **If checks pass:** Proceed to Step 8.
- **If checks fail:**
  1. Identify the failure: `gh pr checks` then `gh run view <run-id> --log-failed`.
  2. Spawn the `debugger` subagent with the failure context to diagnose and fix the issue.
  3. Apply the fix on the same branch, commit, and push.
  4. Repeat from the start of Step 7. Max 3 retries.
  5. If still failing after 3 retries, stop and ask the user for help.

**Step 8: Merge the PR and clean up.**
```bash
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
```
- **If merge conflict:**
  1. Rebase onto the default branch: `git fetch origin main && git rebase origin/main`.
  2. Force-push safely: `git push --force-with-lease`.
  3. Wait for CI again (return to Step 7). Max 1 retry.
  4. If the conflict persists, stop and ask the user for help.

**Step 9: Clean up the session.**
Run `/clean` to clear the conversation context. This ensures a fresh start for the next task.

### After Making a Mistake

- Add a specific rule to "Mistakes to Avoid" at the bottom of this file.

---

## Quality Standards

Before considering any task complete:

- **Be your own reviewer.** Critique the implementation. Would this pass code review? What would a senior engineer question?
- **Prove it works.** Don't just write code — run it. Show test output. Diff behavior if relevant.
- **If the first solution is mediocre, scrap it.** Use everything learned from the first attempt to implement the elegant solution.
- **Ask clarifying questions upfront.** Ambiguity leads to wasted work. Get specifics before implementing.

---

## Project Overview

Jesse is a Python trading system for backtesting and forward testing perpetual futures strategies on BTC/USDT. Designed for rapid strategy iteration with minimal boilerplate.

**Goals:** Easy strategy development, multi-timeframe support (1m–1w), orderflow strategies (OI, CVD), paper trading with crash recovery, win rate and profit factor metrics.

**Not v1:** Live trading, order book data, ML, trailing stops, fees, auto-optimization.

---

## Architecture

```
Data Provider → Engine → Strategy → Executor → Alerts
                  ↓
           Portfolio Manager
                  ↓
      Persistence (SQLite + Parquet)
```

**Tech:** Python 3.11+, asyncio, ccxt, Parquet (pyarrow), SQLite (aiosqlite), httpx, Plotly, Pydantic, Railway.

---

## File Structure

```
jesse/
├── CLAUDE.md -> docs/CLAUDE.md
├── src/
│   ├── core/          # types, engine, portfolio, timeframe
│   ├── data/          # provider, historical, live, orderflow, cache
│   ├── execution/     # executor, backtest, paper, sl_tp
│   ├── strategy/      # base, examples/
│   ├── analysis/      # metrics, charts
│   ├── alerts/        # discord
│   ├── persistence/   # database, models
│   └── config.py
├── strategies/        # User strategies
├── data/              # Runtime (gitignored)
├── output/            # Charts/reports (gitignored)
├── tests/
├── docs/              # PRD, ARCHITECTURE, TASKS, this file
├── main.py
└── pyproject.toml
```

---

## Key Interfaces

```python
# Strategy — implement this
class Strategy(ABC):
    timeframes: list[str] = ['1m']
    
    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        pass

# Signals
Signal.open_long(size_percent=1.0, stop_loss=95000, take_profit=105000)
Signal.open_short(size_percent=1.0, stop_loss=105000, take_profit=95000)
Signal.close(position_id="...")

# Data access
data['1m'].latest              # Current candle
data['4h'].history             # Historical candles
data['1m'].latest.cvd          # Cumulative volume delta
data['1m'].latest.open_interest
```

---

## Critical Details

**Multi-timeframe:** Strategy declares timeframes, `on_candle()` fires on every 1m close, all timeframes delivered simultaneously.

**SL/TP resolution:** When both hit in one candle, drill down to lower timeframes (4h→1h→15m→5m→1m) to determine which hit first. If ambiguous at 1m: assume SL (conservative).

**Positions:** Multiple independent positions, each with own SL/TP, size as % of equity, no hedging.

**CVD:** Prefer exchange data, fallback: `cvd += volume * sign(close - open)`.

**Execution:** Backtest fills at close, paper fills at market, no fees.

---

## Commands

```bash
# Testing
pytest                      # All tests
pytest --cov=src           # With coverage
pytest tests/test_sl_tp.py # Specific file

# Type checking
mypy src/
```

---

## Configuration

See `ARCHITECTURE.md` Section 8 for full configuration and environment variables.

---

## Error Handling

See `ARCHITECTURE.md` Section 7 for error handling strategy.

---

## Principles

1. **Strategy simplicity** — Minimal interface
2. **Same code, both modes** — Strategy doesn't know backtest vs live
3. **Fail safe** — Persist state before risky operations
4. **Async everywhere** — All I/O uses asyncio
5. **Clear separation** — Data, execution, strategy, persistence are independent

---

## Data Structures

See `PRD.md` Section 4 for data structure specifications and `ARCHITECTURE.md` for component interfaces.

---

## Common Tasks

**Add a strategy:**
```python
# strategies/my_strategy.py
from src.strategy.base import Strategy
from src.core.types import Signal, MultiTimeframeData, Portfolio

class MyStrategy(Strategy):
    timeframes = ['1m', '4h']
    
    def on_candle(self, data: MultiTimeframeData, portfolio: Portfolio) -> list[Signal]:
        # Your logic here
        return []
```

**Run backtest:**
```python
engine = Engine(
    strategy=MyStrategy(),
    data_provider=HistoricalDataProvider(symbol="BTC/USDT:USDT", start="2024-01-01", end="2024-12-01"),
    executor=BacktestExecutor(initial_balance=10000)
)
results = engine.run()
```

**Run paper trading:**
```python
engine = Engine(
    strategy=MyStrategy(),
    data_provider=LiveDataProvider(symbol="BTC/USDT:USDT"),
    executor=PaperExecutor(initial_balance=10000),
    alerter=DiscordAlerter(webhook_url="..."),
    persist=True
)
engine.run()  # Runs forever
```

---

## Mistakes to Avoid

*Claude: After any correction, add a rule here. Be specific. Keep iterating until mistake rate drops.*

<!-- 
Format: "Don't X — do Y instead" or "Always X before Y"
Examples:
- Don't use `datetime.now()` — use `datetime.utcnow()` for consistency
- Always check `portfolio.has_position()` before opening new positions
- Parquet files must be closed before reading again
-->
