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

### During Development — Orchestrator Pattern

**You are the orchestrator.** Your role is to coordinate subagents, verify results, and make decisions. Do NOT write implementation code directly. All code generation of more than ~10 lines goes to a subagent via the Task tool. This preserves your context window for coordination across the full task lifecycle.

**Subagent roster:**

| Subagent | How to spawn | Purpose | Writes code? |
|----------|-------------|---------|-------------|
| Planner | Task tool (`subagent_type=Explore`) | Analyze code, produce implementation plan | No |
| Implementer | Task tool (`subagent_type=general-purpose`) | Execute approved plan, write code + tests | Yes |
| Code reviewer | `code-reviewer` agent | Review PR for bugs, security, style | No |
| Debugger | `debugger` agent | Diagnose and fix errors, CI failures | Yes |

**Development flow:**

1. **Plan**: Use the Task tool to spawn an Explore subagent. Pass it the task description, file structure, and relevant docs. It reads code and returns an implementation plan. Present the plan to the user for approval.
2. **Implement**: After approval, use the Task tool to spawn an implementation subagent. Pass it the full approved plan and CLAUDE.md conventions. The subagent writes all code and tests.
3. **Verify**: After the subagent completes, run the full verify suite (lint, format, typecheck, test). If verification fails, spawn the `debugger` agent for test failures or a Task subagent for lint/type errors.
4. When stuck or going in circles, stop. Re-plan before continuing.

**When the orchestrator acts directly** (exceptions):
- Git operations (commit, branch, push, merge)
- Running commands (tests, linters, CI checks)
- Trivial fixes (1-2 lines: typo, import, format issue)
- Task tracker updates
- Skill invocations (`/docs-consolidator`, `/ci-cd-pipeline`)

**Verification protocol**: After any subagent writes code, the orchestrator runs the full verify suite before proceeding. Never trust subagent output without verification.

**Progress tracking**: Use TaskCreate to register each development and pipeline step. Set `owner` to identify which agent handles it (e.g., "Planner", "Implementer", "Code reviewer", "Debugger", or "Orchestrator" for steps you run directly). Mark `in_progress` when starting, `completed` when done. The user sees live progress via `Ctrl+T`.

### After Completing a Task — Autonomous Pipeline

Run this pipeline after every completed task. No user input required unless a step fails and cannot be auto-resolved.

**Step 1: Verify locally.**
Run the project's linting, formatting, type checking, and test commands. Check the Commands section of this file or `pyproject.toml`/`package.json`/`Makefile` for the exact commands. Fix any failures before proceeding.

**Step 2: Documentation and CI/CD audit (parallel).**
Run these concurrently — they are independent:
- `/docs-consolidator` — audit and sync project docs
- `/ci-cd-pipeline` — ensure GitHub Actions matches current state

Skip either if the skill is unavailable. Wait for both to complete before proceeding.

**Step 3: Commit all changes.**
Stage and commit everything from the task and from Step 2. Write a concise, descriptive commit message. Use conventional commit prefixes when appropriate (`feat:`, `fix:`, `chore:`, `docs:`, `ci:`, `refactor:`, `test:`).

**Step 4: Push to a new branch and open a PR.**
- Create a branch with a descriptive name: `<type>/<short-slug>` (e.g., `feat/core-types`, `fix/timestamp-bug`, `chore/update-deps`).
- Push and open a PR:
  ```bash
  git checkout -b <branch-name>
  git push -u origin <branch-name>
  gh pr create --fill
  ```

**Step 5: Code review and CI (parallel).**
Start both immediately after opening the PR:

- **5a**: Spawn the `code-reviewer` subagent to review the PR.
- **5b**: Run `gh pr checks --watch --fail-fast` to monitor CI.

Handling results:
- If review returns Critical or Warning findings:
  - **3+ line fixes**: Spawn a Task subagent to apply them. Do not fix directly.
  - **1-2 line fixes**: The orchestrator may apply these directly.
  - Commit and push fixes. CI restarts automatically on the new push.
- If CI fails:
  1. Identify the failure: `gh pr checks` then `gh run view <run-id> --log-failed`.
  2. Spawn the `debugger` subagent with the failure context.
  3. Apply the fix on the same branch, commit, and push.
  4. Max 3 CI retries. If still failing, stop and ask the user for help.
- **Proceed to Step 6 when**: review is clean (APPROVE or only Nits) AND CI passes.

**Step 6: Merge the PR and clean up.**
```bash
gh pr merge --squash --delete-branch
git checkout main && git pull origin main
```
- **If merge conflict:**
  1. Rebase onto the default branch: `git fetch origin main && git rebase origin/main`.
  2. Force-push safely: `git push --force-with-lease`.
  3. Wait for CI again (return to Step 5b). Max 1 retry.
  4. If the conflict persists, stop and ask the user for help.

**Step 7: Clean up the session.**
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
    data_provider=HistoricalDataProvider(symbol="BTC/USDT:USDT"),
    executor=BacktestExecutor(initial_balance=10000),
    start=datetime(2024, 1, 1),
    end=datetime(2024, 12, 1),
)
results = await engine.run()
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

- Always use timezone-aware datetimes (`timezone.utc`) — Parquet strips timezone info, so re-add it when reading back.
- Don't use `== 0.0` for float sentinel checks — use `None` sentinel instead to avoid ambiguity with legitimate zero values.
- Always run the planning subagent before implementing a task — even when the scope seems obvious. The planner catches bugs, edge cases, and design issues that are easy to miss when jumping straight to code.

<!--
Format: "Don't X — do Y instead" or "Always X before Y"
-->
