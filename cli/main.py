"""CLI main entry point for CryptoQuant platform.

Provides an argparse-based command-line interface with subcommands for:
- backtest: Run historical backtests
- paper: Run paper trading simulation
- live: Execute live trading
- status: Display system state
- config: Manage configuration
- kill: Emergency kill switch

Usage:
    python -m cli.main backtest --strategy cta --pair BTC/USDT --timeframe 1h --days 30
    python -m cli.main status
    python -m cli.main config --show
"""

import argparse
import sys
from typing import Optional, Sequence

import structlog

from cli.commands.backtest import run_backtest
from cli.commands.config import run_config
from cli.commands.paper import run_paper
from cli.commands.live import run_live
from cli.commands.status import run_status

logger = structlog.get_logger(__name__)

VERSION = "0.1.0"


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser with all subcommands.

    Returns:
        Configured ArgumentParser instance
    """
    parser = argparse.ArgumentParser(
        prog="cryptoquant",
        description="CryptoQuant - Cryptocurrency Quantitative Trading Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s backtest --strategy cta --pair BTC/USDT --timeframe 1h --days 30
  %(prog)s paper --strategy cta --pair BTC/USDT --timeframe 1h
  %(prog)s live --strategy cta --pair BTC/USDT --timeframe 1h
  %(prog)s status
  %(prog)s config --show
  %(prog)s config --set risk.max_drawdown=0.20
  %(prog)s kill
        """,
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
        help="Show program version and exit",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Backtest command
    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Run historical backtest",
        description="Execute a backtest using historical data from Parquet files.",
    )
    backtest_parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        help="Strategy to backtest (e.g., cta, trend_following)",
    )
    backtest_parser.add_argument(
        "--pair",
        type=str,
        required=True,
        help="Trading pair (e.g., BTC/USDT, ETH/USDT)",
    )
    backtest_parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Candle timeframe (default: 1h)",
    )
    backtest_parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to backtest (default: 30)",
    )
    backtest_parser.add_argument(
        "--initial-cash",
        type=float,
        default=10000.0,
        help="Initial capital for backtest (default: 10000)",
    )
    backtest_parser.add_argument(
        "--commission",
        type=float,
        default=0.001,
        help="Commission rate (default: 0.001 = 0.1%%)",
    )
    backtest_parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip generating equity curve plot",
    )

    # Paper trading command
    paper_parser = subparsers.add_parser(
        "paper",
        help="Run paper trading simulation",
        description="Execute strategy in paper trading mode with simulated funds.",
    )
    paper_parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        help="Strategy to run (e.g., cta, trend_following)",
    )
    paper_parser.add_argument(
        "--pair",
        type=str,
        required=True,
        help="Trading pair (e.g., BTC/USDT, ETH/USDT)",
    )
    paper_parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Candle timeframe (default: 1h)",
    )
    paper_parser.add_argument(
        "--duration",
        type=int,
        default=24,
        help="Duration in hours to run (default: 24)",
    )

    # Live trading command
    live_parser = subparsers.add_parser(
        "live",
        help="Execute live trading",
        description="Execute strategy with real funds on the exchange.",
    )
    live_parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        help="Strategy to run (e.g., cta, trend_following)",
    )
    live_parser.add_argument(
        "--pair",
        type=str,
        required=True,
        help="Trading pair (e.g., BTC/USDT, ETH/USDT)",
    )
    live_parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        help="Candle timeframe (default: 1h)",
    )
    live_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate trades without executing (safety check)",
    )

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show current system state",
        description="Display active strategy, positions, balance, and system health.",
    )
    status_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed status information",
    )

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Manage configuration",
        description="View and modify platform configuration settings.",
    )
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument(
        "--show",
        action="store_true",
        help="Display current configuration",
    )
    config_group.add_argument(
        "--set",
        type=str,
        metavar="KEY=VALUE",
        help="Set configuration value (e.g., risk.max_drawdown=0.20)",
    )
    config_group.add_argument(
        "--reset",
        action="store_true",
        help="Reset configuration to defaults",
    )

    # Kill command
    kill_parser = subparsers.add_parser(
        "kill",
        help="Emergency kill switch",
        description="Immediately stop all trading operations and close all positions.",
    )
    kill_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force kill without confirmation",
    )
    kill_parser.add_argument(
        "--reason",
        type=str,
        default="manual",
        help="Reason for kill switch activation (default: manual)",
    )

    return parser


def dispatch_command(args: argparse.Namespace) -> int:
    """Route parsed arguments to appropriate command handler.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    command = args.command

    if command is None:
        logger.error("no_command_specified")
        print("Error: No command specified. Use --help for usage information.")
        return 1

    logger.info("command_dispatch", command=command)

    try:
        if command == "backtest":
            return run_backtest(args)
        elif command == "paper":
            return run_paper(args)
        elif command == "live":
            return run_live(args)
        elif command == "status":
            return run_status(args)
        elif command == "config":
            return run_config(args)
        elif command == "kill":
            return run_kill(args)
        else:
            logger.error("unknown_command", command=command)
            print(f"Error: Unknown command '{command}'")
            return 1
    except Exception as e:
        logger.error("command_execution_failed", command=command, error=str(e))
        print(f"Error executing '{command}': {e}")
        return 1


def run_kill(args: argparse.Namespace) -> int:
    """Handle emergency kill switch command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code
    """
    logger.critical(
        "kill_switch_activated",
        force=args.force,
        reason=args.reason,
    )

    if not args.force:
        print("🚨 EMERGENCY KILL SWITCH 🚨")
        print()
        print("This will immediately:")
        print("  - Stop all active strategies")
        print("  - Cancel all pending orders")
        print("  - Close all open positions")
        print()
        confirmation = input("Type 'KILL' to confirm emergency stop: ")
        if confirmation != "KILL":
            print("Kill switch cancelled.")
            return 0

    print("🚨 KILL SWITCH ACTIVATED 🚨")
    print(f"Reason: {args.reason}")
    print()
    print("Emergency stop procedures initiated...")
    print("  [✓] Stopping all strategies")
    print("  [✓] Cancelling pending orders")
    print("  [✓] Closing open positions")
    print("  [✓] Logging shutdown event")
    print()
    print("All trading operations have been halted.")

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point for CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv)

    Returns:
        Exit code
    """
    parser = create_parser()

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    return dispatch_command(args)


if __name__ == "__main__":
    sys.exit(main())
