"""Backtest Wick Inversion on BTC/USDT 1h, 2023-2025, 100 USDT."""

from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd

from cryptoquant.data.cache import DataCache
from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.wick import WickInversion


def run():
    start_date = datetime(2019, 1, 1)
    end_date = datetime(2026, 6, 1)
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)

    print("=" * 70)
    print("  Wick Inversion — BTC/USDT 1h | 2023-01-01 → 2025-12-31")
    print("  Initial Capital: 100 USDT")
    print("=" * 70)

    # Data
    print("\n[1/3] Fetching data from OKX...")
    store = OHLCVStore(db_path="data/cryptoquant.db")
    fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=300)
    cache = DataCache(store=store, fetcher=fetcher)

    df = cache.get_ohlcv(
        exchange="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        start=start_ms,
        end=end_ms,
    )
    print(f"  Got {len(df)} candles: {df.index[0]} → {df.index[-1]}")

    # Backtest
    print("\n[2/3] Running backtest...")
    strategy = WickInversion()
    engine = BacktestEngine(
        initial_capital=10000,
        commission=strategy.params["commission"],
        slippage=0.0005,
    )
    result = engine.run(
        df,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=strategy.params["stop_pct"],
        take_profit_pct=strategy.params["target_pct"],
        max_hold_bars=strategy.params["hold_hours"],
    )

    # Report
    print("\n[3/3] Report:\n")
    m = result.metrics

    def fmt(ts):
        return pd.Timestamp(ts, unit="ms").strftime("%Y-%m-%d %H:%M")

    print(f"  Initial Capital:     {result.initial_capital:>10.2f} USDT")
    print(f"  Final Equity:        {result.final_equity:>10.2f} USDT")
    print(f"  Total Return:        {m.total_return_pct:>+9.2f}%")
    print(f"  Annualized Return:   {m.annualized_return_pct:>+9.2f}%")
    print(f"  Sharpe Ratio:        {m.sharpe_ratio:>10.4f}")
    print(f"  Sortino Ratio:       {m.sortino_ratio:>10.4f}")
    print(f"  Max Drawdown:        {m.max_drawdown_pct:>9.2f}%")
    print(f"  Max DD Duration:     {m.max_drawdown_days:>10d} days")
    print()
    print(f"  Total Trades:        {m.total_trades:>10d}")
    print(f"  Win Rate:            {m.win_rate_pct:>9.2f}%")
    print(f"  Profit Factor:       {m.profit_factor:>10.4f}")
    print(f"  Avg Win:             {m.avg_win_pct:>+9.4f}%")
    print(f"  Avg Loss:            {m.avg_loss_pct:>+9.4f}%")
    print(f"  Avg Hold:            {m.avg_hold_hours:>9.1f} hours")
    print()

    # Exit breakdown
    print("  EXIT BREAKDOWN:")
    exit_counts = Counter(t.exit_reason for t in result.trades)
    for reason, count in exit_counts.most_common():
        pct = count / m.total_trades * 100 if m.total_trades > 0 else 0
        trades_r = [t for t in result.trades if t.exit_reason == reason]
        avg = np.mean([t.pnl_pct for t in trades_r])
        print(f"    {reason:<20s} {count:>5d} ({pct:>5.1f}%)  avg={avg:>+7.4f}%")

    # Monthly returns
    print("\n  MONTHLY RETURNS:")
    if len(m.monthly_returns) > 0:
        for date, ret in m.monthly_returns.items():
            bar = "+" * max(0, int(ret / 2)) if ret > 0 else "-" * max(0, int(-ret / 2))
            print(f"    {date.strftime('%Y-%m')}  {ret:>+7.2f}%  {bar}")

    # Top drawdowns
    print("\n  TOP DRAWDOWNS:")
    for dd in m.drawdown_periods[:5]:
        print(f"    {fmt(dd['start'])} → {fmt(dd['end'])}: {dd['depth_pct']:.2f}% ({dd['days']}d)")

    # Last 10 trades
    print("\n  LAST 10 TRADES:")
    print(f"    {'#':>4} {'Entry':<18} {'Entry$':>10} {'Exit$':>10} {'PnL':>8} {'Reason':<15}")
    for t in result.trades[-10:]:
        print(f"    {t.id:>4} {fmt(t.entry_time):<18} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.pnl_pct:>+7.2f}% {t.exit_reason:<15}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    run()
