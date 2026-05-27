"""Parameter optimization CLI.

Usage:
    # Grid search with train/test split
    python -m backtest.optimize_cli -s cta -p BTC/USDT -t 1h --train-days 180 --test-days 60

    # Grid search with date ranges
    python -m backtest.optimize_cli -s cta --train-start 2024-01-01 --train-end 2024-09-30 --test-start 2024-10-01 --test-end 2024-12-31

    # Random search (faster for large spaces)
    python -m backtest.optimize_cli -s cta --random --trials 50 --train-days 365 --test-days 90

    # Custom parameter ranges
    python -m backtest.optimize_cli -s cta --fast-ma 5-20 --slow-ma 20-60 --ma-types sma,ema --train-days 180
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.optimizer import ParameterOptimizer, SearchSpace, save_results


def parse_range(value: str):
    """Parse 'min-max' or 'min-max-step' range string."""
    parts = value.split("-")
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    elif len(parts) == 3:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    else:
        raise ValueError(f"Invalid range format: {value}. Use 'min-max' or 'min-max-step'")


def parse_float_range(value: str):
    """Parse 'min-max' or 'min-max-step' float range string."""
    parts = value.split("-")
    if len(parts) == 2:
        return (float(parts[0]), float(parts[1]))
    elif len(parts) == 3:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    else:
        raise ValueError(f"Invalid range format: {value}. Use 'min-max' or 'min-max-step'")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="CryptoQuant Parameter Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Grid search with train/test split (last 180/60 days)
  python -m backtest.optimize_cli -s cta --train-days 180 --test-days 60

  # Grid search with date ranges
  python -m backtest.optimize_cli -s cta \\
    --train-start 2024-01-01 --train-end 2024-09-30 \\
    --test-start 2024-10-01 --test-end 2024-12-31

  # Random search (faster for large spaces)
  python -m backtest.optimize_cli -s cta --random --trials 50 --train-days 365

  # Custom parameter ranges
  python -m backtest.optimize_cli -s cta \\
    --fast-ma 5-20 --slow-ma 20-60 --ma-types sma,ema \\
    --train-days 180 --test-days 60

  # Walk-forward: optimize on 6 months, validate on 2 months
  python -m backtest.optimize_cli -s cta -p BTC/USDT -t 1h \\
    --train-start 2024-01-01 --train-end 2024-06-30 \\
    --test-start 2024-07-01 --test-end 2024-08-31
""",
    )

    # Strategy and data
    parser.add_argument("--strategy", "-s", default="cta", help="Strategy name (default: cta)")
    parser.add_argument("--pair", "-p", default="BTC/USDT", help="Trading pair")
    parser.add_argument("--timeframe", "-t", default="1h", help="Candle timeframe")

    # Train period
    parser.add_argument("--train-days", type=int, help="Training period in days")
    parser.add_argument("--train-start", help="Training start date (e.g. 2024-01-01)")
    parser.add_argument("--train-end", help="Training end date (e.g. 2024-06-30)")

    # Test period
    parser.add_argument("--test-days", type=int, help="Test/validation period in days")
    parser.add_argument("--test-start", help="Test start date")
    parser.add_argument("--test-end", help="Test end date")

    # Search mode
    parser.add_argument("--random", action="store_true", help="Use random search instead of grid")
    parser.add_argument("--trials", type=int, default=50, help="Number of random trials (default: 50)")

    # CTA-specific parameter ranges
    parser.add_argument("--fast-ma", help="Fast MA range (e.g. 5-20)")
    parser.add_argument("--slow-ma", help="Slow MA range (e.g. 20-60)")
    parser.add_argument("--ma-types", help="MA types to try (e.g. sma,ema)")
    parser.add_argument("--atr-stop", help="ATR stop multiplier range (e.g. 1.0-3.0)")
    parser.add_argument("--atr-take", help="ATR take multiplier range (e.g. 2.0-5.0)")
    parser.add_argument("--adx-thresh", help="ADX threshold range (e.g. 15-35)")

    # Filters
    parser.add_argument("--no-rsi", action="store_true", help="Disable RSI filter")
    parser.add_argument("--no-adx", action="store_true", help="Disable ADX filter")
    parser.add_argument("--no-atr-exit", action="store_true", help="Disable ATR exit")
    parser.add_argument("--no-regime", action="store_true", help="Disable regime filter")

    # Output
    parser.add_argument("--top", type=int, default=10, help="Number of top results to show (default: 10)")
    parser.add_argument("--validate-top", type=int, default=20, help="Top N train results to validate on test (default: 20)")
    parser.add_argument("--save", metavar="FILE", help="Save results to JSON file (default: logs/optimizer_{strategy}_{pair}_{time}.json)")
    parser.add_argument("--no-save", action="store_true", help="Do not save results to file")

    # Cash/fees
    parser.add_argument("--cash", type=float, default=10000, help="Initial cash (default: 10000)")
    parser.add_argument("--commission", type=float, default=0.001, help="Commission rate")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Slippage rate")

    args = parser.parse_args(argv)

    # Default train period
    if not args.train_days and not args.train_start:
        args.train_days = 180

    # Build search space
    fast_ma = parse_range(args.fast_ma) if args.fast_ma else (5, 20)
    slow_ma = parse_range(args.slow_ma) if args.slow_ma else (20, 60)
    ma_types = args.ma_types.split(",") if args.ma_types else ["sma", "ema"]

    space = SearchSpace.for_cta(
        fast_ma_range=fast_ma,
        slow_ma_range=slow_ma,
        ma_types=ma_types,
        atr_stop_range=parse_float_range(args.atr_stop) if args.atr_stop else None,
        atr_take_range=parse_float_range(args.atr_take) if args.atr_take else None,
        adx_threshold_range=parse_float_range(args.adx_thresh) if args.adx_thresh else None,
        use_rsi=not args.no_rsi,
        use_adx=not args.no_adx,
        use_atr_exit=not args.no_atr_exit,
        use_regime=not args.no_regime,
    )

    grid_size = len(space.generate_grid())
    print(f"Strategy: {args.strategy} | Pair: {args.pair} | Timeframe: {args.timeframe}")
    print(f"Search space: {grid_size} combinations")
    if args.random:
        print(f"Mode: Random search ({args.trials} trials)")
    else:
        print(f"Mode: Grid search")
    print()

    optimizer = ParameterOptimizer(
        strategy_name=args.strategy,
        pair=args.pair,
        timeframe=args.timeframe,
        initial_cash=args.cash,
        commission=args.commission,
        slippage=args.slippage,
    )

    common_kwargs = dict(
        train_days=args.train_days,
        test_days=args.test_days,
        train_start=args.train_start,
        train_end=args.train_end,
        test_start=args.test_start,
        test_end=args.test_end,
        top_n=args.validate_top,
    )

    if args.random:
        results = optimizer.random_search(space, n_trials=args.trials, **common_kwargs)
    else:
        results = optimizer.grid_search(space, **common_kwargs)

    # Filter out errors
    valid_results = [r for r in results if r.train_result.error is None]
    if not valid_results:
        print("No valid results found. Check data availability.")
        sys.exit(1)

    # Print results
    ParameterOptimizer.print_top_results(valid_results, n=args.top)

    # Save results to JSON
    if not args.no_save:
        if args.save:
            save_path = args.save
        else:
            pair_slug = args.pair.replace("/", "_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = f"logs/optimizer_{args.strategy}_{pair_slug}_{args.timeframe}_{ts}.json"

        metadata = {
            "strategy": args.strategy,
            "pair": args.pair,
            "timeframe": args.timeframe,
            "search_mode": "random" if args.random else "grid",
            "train_days": args.train_days,
            "test_days": args.test_days,
            "train_start": args.train_start,
            "train_end": args.train_end,
            "test_start": args.test_start,
            "test_end": args.test_end,
            "initial_cash": args.cash,
        }
        actual_path = save_results(valid_results, filepath=save_path, metadata=metadata)
        print(f"\n  Results saved to: {actual_path}")
        print(f"  Load best params: python -c \"from backtest.optimizer import load_best_params; print(load_best_params('{actual_path}'))\"")

    # Overfitting warning
    if args.test_days or args.test_start:
        top = valid_results[0] if valid_results else None
        if top and top.test_result:
            train_ret = top.train_return
            test_ret = top.test_return
            if train_ret > 0 and abs(test_ret) < abs(train_ret) * 0.3:
                print("⚠️  WARNING: Test return much lower than train — possible overfitting!")
                print(f"   Train: {train_ret:.2%} vs Test: {test_ret:.2%}")
                print(f"   Consider: reducing parameter space, using longer train period, or simpler strategy")
            elif test_ret < 0 and train_ret > 0:
                print("⚠️  WARNING: Positive train return but negative test return — likely overfitting!")


if __name__ == "__main__":
    main()
