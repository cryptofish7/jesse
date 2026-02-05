"""Jesse Trading System — CLI entry point."""

import argparse
import asyncio
import logging
import sys

from src.config import settings, setup_logging

logger = logging.getLogger(__name__)


async def cmd_backtest(args: argparse.Namespace) -> None:
    """Run a backtest with the specified strategy."""
    logger.info(
        "Backtest requested: strategy=%s, start=%s, end=%s, balance=%s",
        args.strategy,
        args.start,
        args.end,
        args.initial_balance,
    )
    print(
        f"Backtest mode: strategy={args.strategy}, "
        f"start={args.start}, end={args.end}, "
        f"initial_balance={args.initial_balance}"
    )
    print("(Not yet implemented)")


async def cmd_forward_test(args: argparse.Namespace) -> None:
    """Run forward testing (paper trading) with the specified strategy."""
    logger.info(
        "Forward test requested: strategy=%s, balance=%s",
        args.strategy,
        args.initial_balance,
    )
    print(
        f"Forward test mode: strategy={args.strategy}, "
        f"initial_balance={args.initial_balance}"
    )
    print("(Not yet implemented)")


async def cmd_fetch_data(args: argparse.Namespace) -> None:
    """Fetch and cache historical data."""
    logger.info(
        "Fetch data requested: symbol=%s, timeframe=%s, start=%s, end=%s",
        args.symbol,
        args.timeframe,
        args.start,
        args.end,
    )
    print(
        f"Fetch data: symbol={args.symbol}, timeframe={args.timeframe}, "
        f"start={args.start}, end={args.end}"
    )
    print("(Not yet implemented)")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="jesse",
        description="Jesse — BTC/USDT perpetual futures trading system",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # backtest
    bt = subparsers.add_parser("backtest", help="Run a backtest")
    bt.add_argument("--strategy", required=True, help="Strategy class name")
    bt.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    bt.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    bt.add_argument(
        "--initial-balance",
        type=float,
        default=settings.initial_balance,
        help=f"Initial balance in USDT (default: {settings.initial_balance})",
    )

    # forward-test
    ft = subparsers.add_parser("forward-test", help="Run forward testing (paper trading)")
    ft.add_argument("--strategy", required=True, help="Strategy class name")
    ft.add_argument(
        "--initial-balance",
        type=float,
        default=settings.initial_balance,
        help=f"Initial balance in USDT (default: {settings.initial_balance})",
    )

    # fetch-data
    fd = subparsers.add_parser("fetch-data", help="Fetch and cache historical data")
    fd.add_argument(
        "--symbol",
        default=settings.symbol,
        help=f"Trading symbol (default: {settings.symbol})",
    )
    fd.add_argument(
        "--timeframe",
        required=True,
        help="Candle timeframe (1m, 5m, 15m, 1h, 4h, 1d, 1w)",
    )
    fd.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    fd.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")

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
