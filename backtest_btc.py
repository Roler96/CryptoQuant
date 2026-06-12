"""Backtest BTC/USDT from 2024-01-01 to 2025-05-30 with 100 USDT initial capital."""

from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd

from cryptoquant.data.cache import DataCache
from cryptoquant.data.fetcher import OHLCVFetcher
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.types import BacktestResult
from strategies.example.ma_cross import MACrossover


def print_detailed_report(result: BacktestResult):
    """Print comprehensive backtest report."""
    m = result.metrics

    def fmt_time(ts_ms: int) -> str:
        return pd.Timestamp(ts_ms, unit="ms").strftime("%Y-%m-%d %H:%M")

    print("=" * 70)
    print(f"  Strategy: {result.strategy_name} v{result.strategy_version}")
    print(f"  Symbol: {result.symbol} | Timeframe: {result.timeframe}")
    print(f"  Period: {fmt_time(result.start_time)} -> {fmt_time(result.end_time)}")
    print("=" * 70)

    print("\n[PERFORMANCE]")
    print(f"  Initial Capital:     {result.initial_capital:>12.2f} USDT")
    print(f"  Final Equity:        {result.final_equity:>12.2f} USDT")
    print(f"  Total Return:        {m.total_return_pct:>+11.2f}%")
    print(f"  Annualized Return:   {m.annualized_return_pct:>+11.2f}%")
    print(f"  Sharpe Ratio:        {m.sharpe_ratio:>12.4f}")
    print(f"  Sortino Ratio:       {m.sortino_ratio:>12.4f}")
    print(f"  Max Drawdown:        {m.max_drawdown_pct:>11.2f}%")
    print(f"  Max DD Duration:     {m.max_drawdown_days:>12d} days")
    print(f"  Volatility (ann):    {m.volatility_annual_pct:>11.2f}%")
    print(f"  VaR 95%:             {m.var_95_pct:>11.4f}%")
    print(f"  CVaR 95%:            {m.cvar_95_pct:>11.4f}%")

    print("\n[TRADE STATISTICS]")
    print(f"  Total Trades:        {m.total_trades:>12d}")
    print(f"  Win Rate:            {m.win_rate_pct:>11.2f}%")
    print(f"  Profit Factor:       {m.profit_factor:>12.4f}")
    print(f"  Avg Win:             {m.avg_win_pct:>+11.4f}%")
    print(f"  Avg Loss:            {m.avg_loss_pct:>+11.4f}%")
    print(f"  Avg Hold:            {m.avg_hold_hours:>11.1f} hours")

    wins = [t for t in result.trades if t.pnl_pct > 0]
    losses = [t for t in result.trades if t.pnl_pct <= 0]

    if wins:
        best = max(wins, key=lambda t: t.pnl_pct)
        print(f"  Best Trade:          {best.pnl_pct:>+11.4f}% @ {fmt_time(best.entry_time)}")
    if losses:
        worst = min(losses, key=lambda t: t.pnl_pct)
        print(f"  Worst Trade:         {worst.pnl_pct:>+11.4f}% @ {fmt_time(worst.entry_time)}")

    print("\n[EXIT REASON BREAKDOWN]")
    print(f"  {'Reason':<20} {'Count':>6} {'Pct':>7} {'Avg PnL':>10} {'Total PnL':>12}")
    print("  " + "-" * 60)
    exit_counts = Counter(t.exit_reason for t in result.trades)
    for reason, count in exit_counts.most_common():
        pct = count / m.total_trades * 100 if m.total_trades > 0 else 0
        trades_by_reason = [t for t in result.trades if t.exit_reason == reason]
        avg_pnl = np.mean([t.pnl_pct for t in trades_by_reason])
        total_pnl = sum(t.pnl_pct for t in trades_by_reason)
        print(f"  {reason:<20} {count:>6} {pct:>6.1f}% {avg_pnl:>+9.4f}% {total_pnl:>+11.4f}%")

    print("\n[MONTHLY RETURNS]")
    if len(m.monthly_returns) > 0:
        print(f"  {'Month':<12} {'Return':>10}")
        print("  " + "-" * 25)
        for date, ret in m.monthly_returns.items():
            month_str = date.strftime("%Y-%m")
            print(f"  {month_str:<12} {ret:>+9.2f}%")
        print("  " + "-" * 25)
        print(f"  {'Total':<12} {m.monthly_returns.sum():>+9.2f}%")
    else:
        print("  No monthly data available")

    print("\n[DRAWDOWN PERIODS (Top 5)]")
    if m.drawdown_periods:
        print(f"  {'Start':<20} {'End':<20} {'Depth':>8} {'Days':>6}")
        print("  " + "-" * 58)
        for dd in m.drawdown_periods[:5]:
            print(f"  {fmt_time(dd['start']):<20} {fmt_time(dd['end']):<20} {dd['depth_pct']:>7.2f}% {dd['days']:>5d}")
    else:
        print("  No drawdown periods")

    print("\n[RECENT TRADES (Last 10)]")
    print(f"  {'#':>3} {'Side':<5} {'Entry Time':<18} {'Entry':>10} {'Exit':>10} {'PnL':>8} {'Reason':<15}")
    print("  " + "-" * 75)
    for t in result.trades[-10:]:
        print(f"  {t.id:>3} {t.side:<5} {fmt_time(t.entry_time):<18} {t.entry_price:>10.2f} {t.exit_price:>10.2f} {t.pnl_pct:>+7.2f}% {t.exit_reason:<15}")

    print("\n" + "=" * 70)


def run_backtest():
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2025, 5, 30)
    start_ms = int(start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)

    print("=" * 70)
    print("  BTC/USDT Backtest: 2024-01-01 to 2025-05-30")
    print("  Initial Capital: 100 USDT")
    print("=" * 70)
    print()

    print("[1/4] Setting up data layer...")
    store = OHLCVStore(db_path="data/cryptoquant.db")
    fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=300)
    cache = DataCache(store=store, fetcher=fetcher)

    print("[2/4] Fetching BTC/USDT 1h data from OKX...")
    print(f"  Range: {start_date} -> {end_date}")
    df = cache.get_ohlcv(
        exchange="okx",
        symbol="BTC/USDT",
        timeframe="1h",
        start=start_ms,
        end=end_ms,
    )
    print(f"  Fetched {len(df)} candles: {df.index[0]} -> {df.index[-1]}")
    print()

    print("[3/4] Running backtest with MACrossover strategy...")
    strategy = MACrossover({"fast": 12, "slow": 26, "signal_type": "long_only"})
    engine = BacktestEngine(
        initial_capital=100,
        commission=0.001,
        slippage=0.0005,
    )
    result = engine.run(
        df,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=3.0,
        take_profit_pct=5.0,
    )
    print(f"  Done. {result.metrics.total_trades} trades simulated.")
    print()

    print("[4/4] Generating detailed report...")
    print()
    print_detailed_report(result)


if __name__ == "__main__":
    run_backtest()
