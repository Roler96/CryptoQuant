"""Backtest runner CLI.

Usage:
    python backtest/run.py --strategy cta --pair BTC/USDT --timeframe 1h --days 90
    python backtest/run.py --strategy cta --pair BTC/USDT --timeframe 1h --start 2024-01-01 --end 2024-06-30
    python backtest/run.py --list-strategies
"""

import argparse
import sys
from pathlib import Path

# Support running as `python backtest/run.py` (add project root to sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.engine import BacktestConfig, BacktestEngine


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="CryptoQuant Backtest Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # By days (last N days from now)
  python backtest/run.py -s cta -p BTC/USDT -t 1h --days 90

  # By date range
  python backtest/run.py -s cta -p BTC/USDT -t 1h --start 2024-01-01 --end 2024-06-30

  # Open-ended (from a date to now)
  python backtest/run.py -s cta -p BTC/USDT -t 4h --start 2024-06-01
""",
    )

    parser.add_argument("--strategy", "-s", help="Strategy name (e.g. cta, trend_following)")
    parser.add_argument("--pair", "-p", default="BTC/USDT", help="Trading pair (default: BTC/USDT)")
    parser.add_argument("--timeframe", "-t", default="1h", help="Candle timeframe (default: 1h)")
    parser.add_argument("--days", "-d", type=int, help="Backtest period in days from now (default: 90)")
    parser.add_argument("--start", help="Start date (e.g. 2024-01-01)")
    parser.add_argument("--end", help="End date (e.g. 2024-12-31)")
    parser.add_argument("--cash", type=float, default=10000, help="Initial cash (default: 10000)")
    parser.add_argument("--commission", type=float, default=0.001, help="Commission rate (default: 0.001)")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Slippage rate (default: 0.0005)")
    parser.add_argument("--no-plot", action="store_true", help="Skip equity curve plot")
    parser.add_argument("--list-strategies", "-l", action="store_true", help="List available strategies")

    args = parser.parse_args(argv)

    # Default: --days 90 if neither --start nor --days specified
    if not args.start and not args.days:
        args.days = 90

    return args


def format_period(args):
    """Format the backtest period for display."""
    if args.start and args.end:
        return f"{args.start} ~ {args.end}"
    elif args.start:
        return f"{args.start} ~ now"
    else:
        return f"last {args.days}d"


def run(argv=None):
    args = parse_args(argv)

    engine = BacktestEngine()

    if args.list_strategies:
        print("Available strategies:")
        for name in engine.get_available_strategies():
            print(f"  - {name}")
        return

    if not args.strategy:
        print("Error: --strategy is required (use --list-strategies to see options)")
        sys.exit(1)

    try:
        strategy = engine.load_strategy(args.strategy)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    config = BacktestConfig(
        initial_cash=args.cash,
        commission=args.commission,
        slippage=args.slippage,
        plot_results=not args.no_plot,
    )
    engine.config = config

    period = format_period(args)
    print(f"Running backtest: {args.strategy} on {args.pair} {args.timeframe} ({period})")
    print(f"  Cash: ${args.cash:,.0f}  Commission: {args.commission:.1%}  Slippage: {args.slippage:.3%}")
    print()

    result = engine.run_backtest(
        strategy,
        args.pair,
        args.timeframe,
        days=args.days,
        start_date=args.start,
        end_date=args.end,
    )

    if result.error:
        print(f"❌ Backtest failed: {result.error}")
        sys.exit(1)

    # 结果摘要
    print("=" * 50)
    print(f"  Strategy:   {result.strategy_name}")
    print(f"  Pair:       {result.pair} {result.timeframe}")
    print(f"  Period:     {period}")
    print(f"  ─────────────────────────────────")
    print(f"  Initial:    ${result.initial_value:,.2f}")
    print(f"  Final:      ${result.final_value:,.2f}")
    print(f"  Return:     {result.total_return:.2%}")
    print(f"  Trades:     {len(result.trades)}")
    print(f"  Sharpe:     {result.sharpe_ratio:.4f}" if result.sharpe_ratio else "  Sharpe:     N/A")
    print(f"  Max DD:     {result.max_drawdown:.2%}" if result.max_drawdown else "  Max DD:     N/A")
    print("=" * 50)

    if result.plot_path:
        print(f"\n📈 Equity plot saved: {result.plot_path}")


if __name__ == "__main__":
    run()
