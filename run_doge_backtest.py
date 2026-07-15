"""Backtest any strategy in strategies/ on 4h data.

Usage:
    uv run python run_doge_backtest.py
    uv run python run_doge_backtest.py --strategy doge_spot_regime_switch
    uv run python run_doge_backtest.py --symbol ASTR/USDT --exchange binance
    uv run python run_doge_backtest.py --start 2021-01-01 --end 2026-07-12 \
        --commission-bps 10 --slippage-bps 2

The strategy is resolved by module name from strategies/, the same way
live_runner resolves trading.strategy, so both run the same class.
"""
import argparse
import sys

import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine, generate_report
from cryptoquant.exceptions import DataError, StrategyError
from cryptoquant.strategy.resolve import resolve_strategy

TIMEFRAME = "4h"


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strategy", default="doge_spot_donchian_sma",
                   help="module name under strategies/ (default: %(default)s)")
    p.add_argument("--symbol", default="DOGE/USDT")
    p.add_argument("--exchange", default="okx")
    p.add_argument("--start", help="UTC date, e.g. 2021-01-01 (default: 1 year ago)")
    p.add_argument("--end", help="UTC date (default: now)")
    p.add_argument("--resample-from", metavar="TF",
                   help="aggregate 4h bars from this stored timeframe (e.g. 1h) "
                        "instead of loading 4h directly. The DOGE research ran "
                        "on 1h aggregated to 4h, and only the 1h table covers "
                        "the full 2021-2026 range.")
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--commission-bps", type=float, default=10.0,
                   help="fee per side in bps (default: %(default)s)")
    p.add_argument("--slippage-bps", type=float, default=5.0,
                   help="slippage per side in bps (default: %(default)s)")
    p.add_argument("--no-trades", action="store_true",
                   help="omit the per-trade table")
    return p


def load_resampled(
    symbol: str, exchange: str, source_tf: str, start_ms: int, end_ms: int
) -> pd.DataFrame:
    """Build 4h bars from a finer stored timeframe, offline."""
    store = OHLCVStore()
    df = store.load(exchange, symbol, source_tf, start=start_ms, end=end_ms)
    store.close()
    if df.empty:
        return df
    print(f"Loaded {len(df)} {source_tf} bars from store "
          f"({df.index[0]} → {df.index[-1]}), aggregating to {TIMEFRAME}")
    return df.resample(TIMEFRAME).agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    ).dropna()


def fetch_data(symbol: str, exchange: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch the symbol's 4h data, using the store as cache."""
    store = OHLCVStore()
    fetcher = OHLCVFetcher(exchange=exchange, testnet=False, max_candles=300)

    df = store.load(exchange, symbol, TIMEFRAME, start=start_ms, end=end_ms)
    if not df.empty and len(df) > 2000:
        print(f"Loaded {len(df)} bars from store ({df.index[0]} → {df.index[-1]})")
        latest = store.get_latest(exchange, symbol, TIMEFRAME)
        if latest and latest > end_ms - 86400000:  # within 1 day of end
            store.close()
            return df
        start_ms = latest if latest else start_ms
    print(f"Fetching {symbol} {TIMEFRAME} from {exchange}...")
    print(f"  Range: {pd.Timestamp(start_ms, unit='ms')} → "
          f"{pd.Timestamp(end_ms, unit='ms')}")

    try:
        df = fetcher.fetch_range(symbol, TIMEFRAME, start_ms, end_ms)
    except DataError as e:
        print(f"  Fetch failed: {e}")
        df = pd.DataFrame()

    if not df.empty:
        store.save(df, exchange, symbol, TIMEFRAME)
        print(f"  Saved {len(df)} bars to store")

    store.close()
    return df


def main() -> None:
    args = build_argparser().parse_args()

    try:
        strategy = resolve_strategy(args.strategy)
    except StrategyError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.now()
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=365)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    if args.resample_from:
        df = load_resampled(
            args.symbol, args.exchange, args.resample_from, start_ms, end_ms
        )
    else:
        df = fetch_data(args.symbol, args.exchange, start_ms, end_ms)
    if df.empty or len(df) < 200:
        print(f"ERROR: Insufficient data ({len(df)} bars). Need at least 200.")
        sys.exit(1)

    df = df[(df.index >= start) & (df.index <= end)]

    print(f"\n{'=' * 60}")
    print(f"Strategy: {strategy.name}  ({args.strategy})")
    print(f"Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")
    print(f"Price range: {df['close'].min():.4f} - {df['close'].max():.4f}")
    print(f"Costs: {args.commission_bps:.0f} bps fee + {args.slippage_bps:.0f} "
          f"bps slippage per side")
    print(f"{'=' * 60}\n")

    engine = BacktestEngine(
        initial_capital=args.capital,
        commission=args.commission_bps / 10_000,
        slippage=args.slippage_bps / 10_000,
    )
    result = engine.run(df, strategy, symbol=args.symbol)

    print(generate_report(result, include_trades=not args.no_trades))


if __name__ == "__main__":
    main()
