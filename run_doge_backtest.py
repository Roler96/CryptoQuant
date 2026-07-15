"""Backtest any strategy in strategies/ on its own timeframe.

Usage:
    uv run python run_doge_backtest.py
    uv run python run_doge_backtest.py --symbol ASTR/USDT --exchange binance
    uv run python run_doge_backtest.py --start 2021-01-01 --end 2026-07-12 \
        --resample-from 1h --commission-bps 10 --slippage-bps 5

The strategy is resolved by module name from strategies/, the same way
live_runner resolves trading.strategy, so both run the same class. The
timeframe defaults to the one the strategy class declares, so a backtest
cannot silently run it on bars it was never designed for.
"""
import argparse
import sys
from typing import cast

import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine, generate_report
from cryptoquant.exceptions import DataError, DataValidationError, StrategyError
from cryptoquant.risk.sizer import FixedSizer
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.resolve import resolve_strategy
from cryptoquant.utils import timeframe_to_timedelta


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", default="doge_donchian_trend",
                   help="module name under strategies/ (default: %(default)s)")
    p.add_argument("--symbol", default="DOGE/USDT")
    p.add_argument("--exchange", default="okx")
    p.add_argument("--timeframe", metavar="TF",
                   help="bar size to run on (default: the strategy's own "
                        "declared timeframe)")
    p.add_argument("--start", help="UTC date, e.g. 2021-01-01 (default: 1 year ago)")
    p.add_argument("--end", help="UTC date (default: now)")
    p.add_argument("--resample-from", metavar="TF",
                   help="aggregate the target bars from this stored timeframe "
                        "(e.g. 1h) instead of loading them directly. The DOGE "
                        "research ran on 1h aggregated to 4h, and only the 1h "
                        "table covers the full 2021-2026 range.")
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--position-pct", type=float, default=100.0,
                   help="fixed percentage of equity per trade (default: %(default)s)")
    p.add_argument("--commission-bps", type=float, default=10.0,
                   help="fee per side in bps (default: %(default)s)")
    p.add_argument("--slippage-bps", type=float, default=5.0,
                   help="slippage per side in bps (default: %(default)s)")
    p.add_argument("--no-trades", action="store_true",
                   help="omit the per-trade table")
    return p


def load_market_context(
    df: pd.DataFrame,
    strategy: Strategy,
    exchange: str,
    timeframe: str,
    start_ms: int,
    end_ms: int,
) -> pd.DataFrame:
    """Join a strategy's auxiliary markets to its primary OHLCV bars."""
    if not strategy.context_markets:
        return df

    result = df.copy()
    store = OHLCVStore()
    try:
        for context in strategy.context_markets:
            context_df = store.load(
                exchange,
                context.historical_symbol,
                timeframe,
                start=start_ms,
                end=end_ms,
            )
            if context_df.empty:
                raise DataValidationError(
                    f"Missing {exchange} context data: "
                    f"{context.historical_symbol} {timeframe}"
                )
            missing = sorted(set(context.columns).difference(context_df.columns))
            if missing:
                raise DataValidationError(
                    f"Context {context.historical_symbol} missing columns: {missing}"
                )
            renamed = context_df.loc[:, list(context.columns)].rename(
                columns={
                    column: f"{context.alias}_{column}"
                    for column in context.columns
                }
            )
            collisions = sorted(set(renamed.columns).intersection(result.columns))
            if collisions:
                raise DataValidationError(
                    f"Context output columns collide with primary data: {collisions}"
                )
            result = result.join(renamed, how="left")
    finally:
        store.close()
    return result


def load_resampled(
    symbol: str, exchange: str, source_tf: str, target_tf: str,
    start_ms: int, end_ms: int,
) -> pd.DataFrame:
    """Build target_tf bars from a finer stored timeframe, offline."""
    store = OHLCVStore()
    df = store.load(exchange, symbol, source_tf, start=start_ms, end=end_ms)
    store.close()
    if df.empty:
        return df
    print(f"Loaded {len(df)} {source_tf} bars from store "
          f"({df.index[0]} → {df.index[-1]}), aggregating to {target_tf}")
    return resample_complete_ohlcv(df, source_tf, target_tf)


def resample_complete_ohlcv(
    df: pd.DataFrame, source_tf: str, target_tf: str
) -> pd.DataFrame:
    """Aggregate OHLCV while rejecting partial target-timeframe buckets."""
    source_delta = timeframe_to_timedelta(source_tf)
    target_delta = timeframe_to_timedelta(target_tf)
    if target_delta <= source_delta or target_delta % source_delta != pd.Timedelta(0):
        raise DataValidationError(
            f"Cannot build complete {target_tf} bars from {source_tf} bars"
        )
    expected = int(target_delta / source_delta)
    resampler = df.resample(target_delta)
    counts = resampler["close"].count()
    bars = resampler.agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    )
    return bars.loc[counts == expected].dropna()


def fetch_data(
    symbol: str, exchange: str, timeframe: str, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """Fetch the symbol's bars at timeframe, using the store as cache."""
    store = OHLCVStore()
    fetcher = OHLCVFetcher(exchange=exchange, testnet=False, max_candles=300)

    requested_start_ms = start_ms
    cached = store.load(
        exchange, symbol, timeframe, start=requested_start_ms, end=end_ms
    )
    if not cached.empty and len(cached) > 2000:
        print(
            f"Loaded {len(cached)} bars from store "
            f"({cached.index[0]} → {cached.index[-1]})"
        )
        latest = store.get_latest(exchange, symbol, timeframe)
        if latest and latest > end_ms - 86400000:  # within 1 day of end
            store.close()
            return cached
        start_ms = latest + 1 if latest else start_ms
    print(f"Fetching {symbol} {timeframe} from {exchange}...")
    print(f"  Range: {pd.Timestamp(start_ms, unit='ms')} → "
          f"{pd.Timestamp(end_ms, unit='ms')}")

    try:
        df = fetcher.fetch_range(symbol, timeframe, start_ms, end_ms)
    except DataError as e:
        print(f"  Fetch failed: {e}")
        df_new = pd.DataFrame()
    else:
        df_new = df

    if not df_new.empty:
        store.save(df_new, exchange, symbol, timeframe)
        print(f"  Saved {len(df_new)} bars to store")

    result = store.load(
        exchange,
        symbol,
        timeframe,
        start=requested_start_ms,
        end=end_ms,
    )
    store.close()
    return result


def main() -> None:
    args = build_argparser().parse_args()

    try:
        strategy = resolve_strategy(args.strategy)
    except StrategyError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    timeframe = args.timeframe or strategy.timeframe
    if strategy.execution_exchange and args.exchange != strategy.execution_exchange:
        print(
            f"ERROR: {strategy.name} requires exchange "
            f"{strategy.execution_exchange}, got {args.exchange}"
        )
        sys.exit(1)
    if strategy.execution_symbol and args.symbol != strategy.execution_symbol:
        print(
            f"ERROR: {strategy.name} trades {strategy.execution_symbol}, "
            f"got {args.symbol}"
        )
        sys.exit(1)
    if not 0 < args.position_pct <= 100:
        print("ERROR: --position-pct must be in (0, 100]")
        sys.exit(1)
    try:
        target = timeframe_to_timedelta(timeframe)
        if args.resample_from and timeframe_to_timedelta(args.resample_from) >= target:
            print(f"ERROR: --resample-from {args.resample_from} is not finer than "
                  f"the {timeframe} bars it would build.")
            sys.exit(1)
    except DataValidationError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    end: pd.Timestamp = (
        cast(pd.Timestamp, pd.Timestamp(args.end))
        if args.end
        else pd.Timestamp.now()
    )
    start: pd.Timestamp = (
        cast(pd.Timestamp, pd.Timestamp(args.start))
        if args.start
        else cast(pd.Timestamp, end - pd.Timedelta(days=365))
    )
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    if args.resample_from:
        df = load_resampled(
            args.symbol, args.exchange, args.resample_from, timeframe, start_ms, end_ms
        )
    else:
        df = fetch_data(args.symbol, args.exchange, timeframe, start_ms, end_ms)
    if df.empty or len(df) < 200:
        print(f"ERROR: Insufficient data ({len(df)} bars). Need at least 200.")
        sys.exit(1)

    df = cast(pd.DataFrame, df.loc[(df.index >= start) & (df.index <= end)])
    try:
        df = load_market_context(
            df, strategy, args.exchange, timeframe, start_ms, end_ms
        )
    except DataValidationError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print(f"Strategy: {strategy.name}  ({args.strategy})")
    print(f"Timeframe: {timeframe}"
          + ("" if args.timeframe is None
             else f"  [OVERRIDE — strategy declares {strategy.timeframe}]"))
    print(f"Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")
    print(f"Price range: {df['close'].min():.4f} - {df['close'].max():.4f}")
    print(f"Costs: {args.commission_bps:.0f} bps fee + {args.slippage_bps:.0f} "
          f"bps slippage per side")
    print(f"Position: {args.position_pct:g}% of equity")
    if strategy.context_markets:
        names = ", ".join(
            f"{item.alias}={item.historical_symbol}" for item in strategy.context_markets
        )
        print(f"Context: {names}")
    print(f"{'=' * 60}\n")

    engine = BacktestEngine(
        initial_capital=args.capital,
        commission=args.commission_bps / 10_000,
        slippage=args.slippage_bps / 10_000,
        sizer=(
            None
            if args.position_pct >= 100
            else FixedSizer(risk_pct=args.position_pct, min_order=0.0)
        ),
    )
    result = engine.run(
        df,
        strategy,
        symbol=args.symbol,
        max_hold_bars=strategy.max_hold_bars,
    )

    print(generate_report(result, include_trades=not args.no_trades))


if __name__ == "__main__":
    main()
