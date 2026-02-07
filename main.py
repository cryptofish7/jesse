"""Jesse Trading System — CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.config import settings, setup_logging

logger = logging.getLogger(__name__)


def _parse_date(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD string into a timezone-aware UTC datetime."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.") from None
    return dt.replace(tzinfo=UTC)


async def cmd_backtest(args: argparse.Namespace) -> None:
    """Run a backtest with the specified strategy."""
    from src.core.engine import Engine
    from src.data.historical import HistoricalDataProvider
    from src.execution.backtest import BacktestExecutor
    from src.strategy.loader import load_strategy

    # Parse dates
    start = _parse_date(args.start)
    end = _parse_date(args.end)

    if end <= start:
        print(f"Error: end date ({args.end}) must be after start date ({args.start})")
        sys.exit(1)

    # Load strategy
    try:
        strategy = load_strategy(args.strategy)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    strategy_name = type(strategy).__name__
    logger.info(
        "Starting backtest: strategy=%s, start=%s, end=%s, balance=%.2f",
        strategy_name,
        args.start,
        args.end,
        args.initial_balance,
    )

    # Create components
    provider = HistoricalDataProvider(symbol=settings.symbol)
    executor = BacktestExecutor(initial_balance=args.initial_balance)

    engine = Engine(
        strategy=strategy,
        data_provider=provider,
        executor=executor,
        start=start,
        end=end,
    )

    try:
        results = await engine.run()
    finally:
        await provider.close()

    if results is None:
        print("Error: Backtest returned no results.")
        sys.exit(1)

    # Print results summary
    print(results.summary())

    # Generate output artifacts
    output_dir = Path(settings.output_path) / strategy_name.lower()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Equity curve chart
    equity_path = output_dir / "equity_curve.html"
    results.plot_equity_curve(equity_path)
    print(f"\nEquity curve chart: {equity_path}")

    # Trades CSV
    trades_path = output_dir / "trades.csv"
    results.export_trades(trades_path)
    print(f"Trades CSV:         {trades_path}")

    logger.info("Backtest complete. Output saved to %s", output_dir)


async def cmd_forward_test(args: argparse.Namespace) -> None:
    """Run forward testing (paper trading) with the specified strategy."""
    from src.alerts.discord import DiscordAlerter
    from src.core.engine import Engine
    from src.data.live import LiveDataProvider
    from src.execution.paper import PaperExecutor
    from src.strategy.loader import load_strategy

    # Load strategy
    try:
        strategy = load_strategy(args.strategy)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    strategy_name = type(strategy).__name__
    logger.info(
        "Starting forward test: strategy=%s, balance=%.2f",
        strategy_name,
        args.initial_balance,
    )

    # Create components
    provider = LiveDataProvider(symbol=settings.symbol)
    executor = PaperExecutor(initial_balance=args.initial_balance)

    # Optional Discord alerter
    alerter: DiscordAlerter | None = None
    if settings.discord_webhook_url:
        alerter = DiscordAlerter(webhook_url=settings.discord_webhook_url)

    engine = Engine(
        strategy=strategy,
        data_provider=provider,
        executor=executor,
        alerter=alerter,
        persist=True,
    )

    print(f"Forward test starting: {strategy_name}")
    print("Press Ctrl+C to stop.")

    try:
        await engine.run()
    finally:
        if alerter is not None:
            await alerter.close()


async def cmd_fetch_data(args: argparse.Namespace) -> None:
    """Fetch and cache historical data."""
    from src.data import cache
    from src.data.historical import HistoricalDataProvider

    symbol = args.symbol
    timeframe = args.timeframe

    # Determine start date
    if args.start is not None:
        start = _parse_date(args.start)
    else:
        # Check cache for existing data
        date_range = cache.get_cache_date_range(symbol, timeframe)
        if date_range is not None:
            # Incremental update: start from last cached timestamp
            start = date_range[1]
            logger.info("Cache exists, incremental update from %s", start)
        else:
            # No cache: default to 4 years ago
            start = datetime.now(UTC) - timedelta(days=4 * 365)
            logger.info("No cache found, fetching from %s", start)

    # Determine end date
    if args.end is not None:
        end = _parse_date(args.end)
    else:
        end = datetime.now(UTC)

    if end <= start:
        print(f"Error: end date must be after start date (start={start}, end={end})")
        sys.exit(1)

    logger.info(
        "Fetching data: symbol=%s, timeframe=%s, start=%s, end=%s",
        symbol,
        timeframe,
        start,
        end,
    )
    print(f"Fetching {symbol} {timeframe} candles from {start:%Y-%m-%d} to {end:%Y-%m-%d}...")

    provider = HistoricalDataProvider(symbol=symbol)
    try:
        candles = await provider.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )
    finally:
        await provider.close()

    # Log summary
    cache_file = cache.cache_path(symbol, timeframe)
    if candles:
        first_ts = candles[0].timestamp
        last_ts = candles[-1].timestamp
        print(
            f"\nFetch complete:"
            f"\n  Date range:  {first_ts:%Y-%m-%d %H:%M} to {last_ts:%Y-%m-%d %H:%M}"
            f"\n  Candles:     {len(candles):,}"
            f"\n  Cache file:  {cache_file}"
        )
    else:
        print("\nNo candles returned for the requested range.")

    logger.info("Fetch data complete: %d candles, cache=%s", len(candles), cache_file)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="jesse",
        description="Jesse — BTC/USDT perpetual futures trading system",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # backtest
    bt = subparsers.add_parser(
        "backtest",
        help="Run a backtest",
        description="Backtest a strategy against historical data.",
    )
    bt.add_argument("--strategy", required=True, help="Strategy class name (e.g., MACrossover)")
    bt.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    bt.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    bt.add_argument(
        "--initial-balance",
        type=float,
        default=settings.initial_balance,
        help=f"Initial balance in USDT (default: {settings.initial_balance})",
    )

    # forward-test
    ft = subparsers.add_parser(
        "forward-test",
        help="Run forward testing (paper trading)",
        description="Run a strategy in paper trading mode with live market data.",
    )
    ft.add_argument("--strategy", required=True, help="Strategy class name (e.g., MACrossover)")
    ft.add_argument(
        "--initial-balance",
        type=float,
        default=settings.initial_balance,
        help=f"Initial balance in USDT (default: {settings.initial_balance})",
    )

    # fetch-data
    fd = subparsers.add_parser(
        "fetch-data",
        help="Fetch and cache historical data",
        description=(
            "Fetch historical candle data from the exchange and cache to Parquet. "
            "Supports incremental updates: if cache exists, only fetches new data."
        ),
    )
    fd.add_argument(
        "--symbol",
        default=settings.symbol,
        help=f"Trading symbol (default: {settings.symbol})",
    )
    fd.add_argument(
        "--timeframe",
        default="1m",
        help="Candle timeframe: 1m, 5m, 15m, 1h, 4h, 1d, 1w (default: 1m)",
    )
    fd.add_argument(
        "--start",
        default=None,
        help="Start date YYYY-MM-DD (default: last cached timestamp, or 4 years ago if no cache)",
    )
    fd.add_argument(
        "--end",
        default=None,
        help="End date YYYY-MM-DD (default: current UTC time)",
    )

    return parser


def main() -> None:
    """Main entry point."""
    setup_logging(settings.log_level)

    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    command_map = {
        "backtest": cmd_backtest,
        "forward-test": cmd_forward_test,
        "fetch-data": cmd_fetch_data,
    }

    handler = command_map[args.command]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
