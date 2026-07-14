"""Backtest DogeSpotDonchianSma on ~1 year of DOGE/USDT 4h data."""
import sys
import time

import pandas as pd

from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.doge_spot_donchian_sma import DogeSpotDonchianSma


SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "DOGE/USDT"
TIMEFRAME = "4h"
EXCHANGE = sys.argv[2] if len(sys.argv) > 2 else "okx"
# ~1 year ago to now (ms)
END_MS = int(pd.Timestamp.now().timestamp() * 1000)
START_MS = int((pd.Timestamp.now() - pd.Timedelta(days=365)).timestamp() * 1000)


def fetch_data() -> pd.DataFrame:
    """Fetch DOGE/USDT 4h data, using store as cache."""
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

    # Fetch in chunks with rate limiting
    cursor = start
    all_chunks = []
    empty_first = False
    while cursor < END_MS:
        try:
            chunk = fetcher.fetch(SYMBOL, TIMEFRAME, limit=300, since=cursor)
        except Exception as e:
            print(f"  Fetch error at {pd.Timestamp(cursor, unit='ms')}: {e}")
            print(f"  Retrying in 3s...")
            time.sleep(3)
            try:
                chunk = fetcher.fetch(SYMBOL, TIMEFRAME, limit=300, since=cursor)
            except Exception as e2:
                print(f"  Retry failed: {e2}")
                break

        if chunk.empty:
            if not all_chunks:
                # First fetch empty — symbol may not have existed this early.
                # Advance cursor by 30 days and retry until we find data.
                print(f"  No data at {pd.Timestamp(cursor, unit='ms')}, skipping ahead 30d...")
                cursor += 30 * 86400000
                continue
            else:
                print(f"  Empty response at cursor {pd.Timestamp(cursor, unit='ms')}")
                break

        all_chunks.append(chunk)
        n = len(chunk)
        last_ts = int(chunk.index[-1].timestamp() * 1000)
        print(f"  Fetched {n} bars, last={chunk.index[-1]}, total so far={sum(len(c) for c in all_chunks)}")

        cursor = last_ts + 1
        if last_ts >= END_MS:
            break
        # Rate limit: OKX allows ~20 req/2s for public endpoints
        time.sleep(0.5)

    if all_chunks:
        df = pd.concat(all_chunks)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        # Save to store
        store.save(df, EXCHANGE, SYMBOL, TIMEFRAME)
        print(f"  Saved {len(df)} bars to store")
    else:
        df = pd.DataFrame()

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
    # OKX spot: 0.1% taker commission, ~0.05% slippage
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=0.001,   # 0.1% per side
        slippage=0.0005,    # 0.05% per side
    )

    strategy = DogeSpotDonchianSma()
    result = engine.run(df, strategy, symbol=SYMBOL)

    m = result.metrics
    print(f"{'='*60}")
    print(f"Strategy: {result.strategy_name} v{result.strategy_version}")
    print(f"Symbol: {result.symbol} | Timeframe: {result.timeframe}")
    print(f"Period: {pd.Timestamp(result.start_time, unit='ms')} → {pd.Timestamp(result.end_time, unit='ms')}")
    print(f"{'='*60}")
    print(f"Total Return:      {m.total_return_pct:+.2f}%")
    print(f"Annualized Return: {m.annualized_return_pct:+.2f}%")
    print(f"Final Equity:      {result.final_equity:,.2f} (from {result.initial_capital:,.2f})")
    print(f"Total Trades:      {m.total_trades}")
    print(f"Win Rate:          {m.win_rate_pct:.1f}%")
    print(f"Profit Factor:     {m.profit_factor:.2f}")
    print(f"Sharpe Ratio:      {m.sharpe_ratio:.2f}")
    print(f"Sortino Ratio:     {m.sortino_ratio:.2f}")
    print(f"Max Drawdown:      {m.max_drawdown_pct:.2f}%")
    print(f"Max DD Days:       {m.max_drawdown_days}")
    print(f"Volatility (ann):  {m.volatility_annual_pct:.2f}%")
    print(f"VaR 95%:           {m.var_95_pct:.2f}%")
    print(f"CVaR 95%:          {m.cvar_95_pct:.2f}%")
    print(f"Avg Win:           {m.avg_win_pct:+.2f}%")
    print(f"Avg Loss:          {m.avg_loss_pct:+.2f}%")
    print(f"Avg Hold Time:     {m.avg_hold_hours:.1f}h")
    print(f"{'='*60}")

    # Print individual trades
    if result.trades:
        print(f"\nTrade-by-trade ({len(result.trades)} trades):")
        print(f"{'ID':>4} {'Side':>5} {'Entry':>10} {'Exit':>10} {'PnL%':>8} {'Hold(h)':>8} {'Exit Reason':>15}")
        print("-" * 65)
        for t in result.trades:
            print(
                f"{t.id:>4} {t.side:>5} {t.entry_price:>10.4f} {t.exit_price:>10.4f} "
                f"{t.pnl_pct:>+8.2f} {t.hold_hours:>8.1f} {t.exit_reason:>15}"
            )

    # Monthly returns
    if not m.monthly_returns.empty:
        print(f"\nMonthly Returns:")
        print(f"{'Month':>12} {'Return%':>8}")
        print("-" * 22)
        for ts, ret in m.monthly_returns.items():
            print(f"{ts.strftime('%Y-%m'):>12} {ret:>+8.2f}")


if __name__ == "__main__":
    main()
