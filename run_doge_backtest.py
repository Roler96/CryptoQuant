"""Backtest DogeSpotDonchianSma on ~1 year of 4h data.

Usage:
    python run_doge_backtest.py [SYMBOL] [EXCHANGE]

Defaults to DOGE/USDT on okx. Other pairs are just different arguments, e.g.
    python run_doge_backtest.py ASTR/USDT binance
"""
import sys

import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine, generate_report
from cryptoquant.exceptions import DataError
from strategies.doge_spot_donchian_sma import DogeSpotDonchianSma


SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "DOGE/USDT"
TIMEFRAME = "4h"
EXCHANGE = sys.argv[2] if len(sys.argv) > 2 else "okx"
# ~1 year ago to now (ms)
END_MS = int(pd.Timestamp.now().timestamp() * 1000)
START_MS = int((pd.Timestamp.now() - pd.Timedelta(days=365)).timestamp() * 1000)


def fetch_data() -> pd.DataFrame:
    """Fetch the configured symbol's 4h data, using the store as cache."""
    store = OHLCVStore()
    fetcher = OHLCVFetcher(exchange=EXCHANGE, testnet=False, max_candles=300)

    # Try loading from store first
    df = store.load(EXCHANGE, SYMBOL, TIMEFRAME, start=START_MS, end=END_MS)
    if not df.empty and len(df) > 2000:
        print(f"Loaded {len(df)} bars from store ({df.index[0]} → {df.index[-1]})")
        # Check if we have recent data
        latest = store.get_latest(EXCHANGE, SYMBOL, TIMEFRAME)
        if latest and latest > END_MS - 86400000:  # within 1 day of end
            store.close()
            return df
        # Otherwise fetch from latest to end
        start = latest if latest else START_MS
    else:
        start = START_MS

    print(f"Fetching {SYMBOL} {TIMEFRAME} from {EXCHANGE}...")
    print(f"  Range: {pd.Timestamp(start, unit='ms')} → {pd.Timestamp(END_MS, unit='ms')}")

    try:
        df = fetcher.fetch_range(SYMBOL, TIMEFRAME, start, END_MS)
    except DataError as e:
        print(f"  Fetch failed: {e}")
        df = pd.DataFrame()

    if not df.empty:
        store.save(df, EXCHANGE, SYMBOL, TIMEFRAME)
        print(f"  Saved {len(df)} bars to store")

    store.close()
    return df


def main():
    df = fetch_data()
    if df.empty or len(df) < 200:
        print(f"ERROR: Insufficient data ({len(df)} bars). Need at least 200.")
        sys.exit(1)

    # Filter to requested range
    start_ts = pd.Timestamp(START_MS, unit="ms")
    end_ts = pd.Timestamp(END_MS, unit="ms")
    df = df[(df.index >= start_ts) & (df.index <= end_ts)]

    print(f"\n{'='*60}")
    print(f"Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")
    print(f"Price range: {df['close'].min():.4f} - {df['close'].max():.4f}")
    print(f"{'='*60}\n")

    # Run backtest with realistic costs
    # OKX and Binance spot both charge 0.1% taker; ~0.05% slippage
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.001,   # 0.1% per side
        slippage=0.0005,    # 0.05% per side
    )

    strategy = DogeSpotDonchianSma()
    result = engine.run(df, strategy, symbol=SYMBOL)

    print(generate_report(result, include_trades=True))


if __name__ == "__main__":
    main()
