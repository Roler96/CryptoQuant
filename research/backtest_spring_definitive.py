"""
Spring Reversal — Definitive Backtest using BacktestEngine
===========================================================

Validates the SpringReversal v1.3.0 strategy class through the actual
BacktestEngine (not custom regime_backtest). Produces canonical benchmark
numbers for docs/research/spring/STRATEGY.md.

Usage:
    uv run python research/backtest_spring_definitive.py
"""

import sys
import os
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.spring import SpringReversal


def fmt(val, spec="+.2f"):
    """Format a number with the given format spec, returning a string."""
    return format(val, spec)


def walk_forward(
    df: pd.DataFrame,
    strategy: SpringReversal,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_hold_bars: int,
    n_splits: int = 7,
) -> list[dict]:
    """Run walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]

        engine = BacktestEngine(
            initial_capital=10_000,
            commission=strategy.params["commission"],
            slippage=0.0005,
            use_lows_for_stops=True,
        )

        result = engine.run(
            split_df,
            strategy,
            symbol="BTC/USDT",
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            max_hold_bars=max_hold_bars,
        )

        results.append({
            "split": s + 1,
            "start": str(split_df.index[0].strftime("%Y-%m")),
            "end": str(split_df.index[-1].strftime("%Y-%m")),
            "trades": result.metrics.total_trades,
            "return_pct": result.metrics.total_return_pct,
            "sharpe": result.metrics.sharpe_ratio,
            "max_dd": result.metrics.max_drawdown_pct,
            "win_rate": result.metrics.win_rate_pct,
            "profitable": result.metrics.total_return_pct > 0,
        })

    return results


def print_separator(title="", char="=", width=70):
    """Print a formatted separator."""
    print()
    print(char * width)
    if title:
        print("  " + title)
        print(char * width)


def main():
    # ── Load data ──────────────────────────────────────────────────
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")

    print_separator("SPRING REVERSAL — DEFINITIVE BACKTEST (BacktestEngine)")
    print()
    print(f"  OKX: {len(df_okx):,} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"  Binance: {len(df_binance):,} bars, {df_binance.index[0]} to {df_binance.index[-1]}")

    # ── Strategy ───────────────────────────────────────────────────
    strategy = SpringReversal()
    print()
    print(f"  Strategy: {strategy.name} v{strategy.version}")
    print(f"  Params: stop={strategy.params['stop_pct']}%, "
          f"target={strategy.params['target_pct']}%, "
          f"hold={strategy.params['hold_hours']}h")
    print(f"  Filters: SMA200={'ON' if strategy.params['sma200_filter'] else 'OFF'}, "
          f"BB %B [{strategy.params['bb_low']}, {strategy.params['bb_high']}) "
          f"={'ON' if strategy.params['bb_filter'] else 'OFF'}")
    print(f"  Commission: {strategy.params['commission']*10000:.0f} bps round-trip")
    print(f"  Slippage: 5 bps")

    stop_pct = strategy.params["stop_pct"]
    target_pct = strategy.params["target_pct"]
    hold_hours = strategy.params["hold_hours"]
    max_hold_bars = hold_hours  # 1h bars = hours

    # ── Full Backtest: OKX ─────────────────────────────────────────
    print_separator("FULL BACKTEST — OKX BTC/USDT 1h (2019-2026)")

    engine = BacktestEngine(
        initial_capital=10_000,
        commission=strategy.params["commission"],
        slippage=0.0005,
        use_lows_for_stops=True,
    )

    result = engine.run(
        df_okx,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=stop_pct,
        take_profit_pct=target_pct,
        max_hold_bars=max_hold_bars,
    )

    m = result.metrics
    trades = result.trades

    exit_counts = Counter(t.exit_reason for t in trades)
    exit_subsets = {}
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse", "end_of_data"]:
        subset = [t for t in trades if t.exit_reason == reason]
        if subset:
            exit_subsets[reason] = {
                "count": len(subset),
                "pct": len(subset) / len(trades) * 100,
                "avg_pnl": np.mean([t.pnl_pct for t in subset]),
                "total_pnl": sum(t.pnl_pct for t in subset),
            }

    max_consec = 0
    consec = 0
    for t in trades:
        if t.pnl_pct <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    print()
    print("  Initial Capital:    10,000 USDT")
    print("  Commission:         5 bps (round-trip)")
    print("  Slippage:           5 bps")
    print()
    print(f"  Total Trades:       {m.total_trades}")
    print(f"  Compound Return:    {fmt(m.total_return_pct, '+.1f')}%")
    print(f"  Annualized Return:  {fmt(m.annualized_return_pct, '+.1f')}%")
    print(f"  Sharpe Ratio:       {fmt(m.sharpe_ratio, '+.2f')}")
    print(f"  Sortino Ratio:      {fmt(m.sortino_ratio, '+.2f')}")
    print(f"  Max Drawdown:       {fmt(m.max_drawdown_pct, '+.1f')}%")
    print(f"  Max DD Duration:    {m.max_drawdown_days} days")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {fmt(m.avg_win_pct, '+.2f')}%")
    print(f"  Avg Loss:           {fmt(m.avg_loss_pct, '+.2f')}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Max Consec Losses:  {max_consec}")
    print(f"  Avg Hold Hours:     {m.avg_hold_hours:.1f}h")
    print()
    print("  Exit Breakdown:")

    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse", "end_of_data"]:
        if reason in exit_subsets:
            es = exit_subsets[reason]
            print(f"    {reason:16s}: {es['count']:4d} ({es['pct']:5.1f}%)  "
                  f"avg={fmt(es['avg_pnl'], '+.2f')}%  total={fmt(es['total_pnl'], '+.1f')}%")

    # MFE analysis
    mfes = [t.mfe_pct for t in trades]
    maes = [t.mae_pct for t in trades]
    time_exits = [t for t in trades if t.exit_reason == "time_exit"]
    profitable_time = sum(1 for t in time_exits if t.mfe_pct > 0)

    print()
    print("  MFE Analysis:")
    print(f"    Mean MFE:   {fmt(np.mean(mfes), '+.2f')}%")
    print(f"    Median MFE: {fmt(np.median(mfes), '+.2f')}%")
    print(f"    Max MFE:    {fmt(np.max(mfes), '+.2f')}%")
    print()
    print(f"    Mean MAE:   {fmt(np.mean(maes), '+.2f')}%")
    print(f"    Median MAE: {fmt(np.median(maes), '+.2f')}%")

    if time_exits:
        print()
        print(f"  Time-exit profitable at some point: {profitable_time}/{len(time_exits)} "
              f"({profitable_time/len(time_exits)*100:.1f}%)")

    # ── Walk-Forward: OKX ─────────────────────────────────────────
    print_separator("WALK-FORWARD VALIDATION — OKX (7 splits, OOS)")

    wf_results = walk_forward(df_okx, strategy, stop_pct, target_pct, max_hold_bars)

    wf_sharpes = []
    wf_positive = 0
    for wr in wf_results:
        wf_sharpes.append(wr["sharpe"])
        if wr["profitable"]:
            wf_positive += 1
        status = "OK" if wr["profitable"] else "!!"
        print(f"  Split {wr['split']}: {wr['start']} -> {wr['end']}  "
              f"trades={wr['trades']:3d}  return={fmt(wr['return_pct'], '+.1f')}%  "
              f"sharpe={fmt(wr['sharpe'], '+.2f')}  dd={fmt(wr['max_dd'], '+.1f')}%  {status}")

    print()
    print(f"  OOS Profitable:  {wf_positive}/{len(wf_results)} splits")
    print(f"  Mean OOS Sharpe: {fmt(np.mean(wf_sharpes), '+.2f')}")
    print(f"  Total OOS Return: {fmt(sum(wr['return_pct'] for wr in wf_results), '+.1f')}%")

    # ── Full Backtest: Binance ─────────────────────────────────────
    print_separator("BINANCE CROSS-VALIDATION — BTC/USDT 1h (2019-2026)")

    engine_b = BacktestEngine(
        initial_capital=10_000,
        commission=strategy.params["commission"],
        slippage=0.0005,
        use_lows_for_stops=True,
    )

    result_b = engine_b.run(
        df_binance,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=stop_pct,
        take_profit_pct=target_pct,
        max_hold_bars=max_hold_bars,
    )

    mb = result_b.metrics

    print()
    print(f"  Total Trades:       {mb.total_trades}")
    print(f"  Compound Return:    {fmt(mb.total_return_pct, '+.1f')}%")
    print(f"  Sharpe Ratio:       {fmt(mb.sharpe_ratio, '+.2f')}")
    print(f"  Win Rate:           {mb.win_rate_pct:.1f}%")
    print(f"  Profit Factor:      {mb.profit_factor:.2f}")
    print(f"  Max Drawdown:       {fmt(mb.max_drawdown_pct, '+.1f')}%")
    print()
    print("  Cross-Exchange Comparison:")
    print(f"  {'Metric':22s} {'OKX':>10s} {'Binance':>10s}")
    print(f"  {'-'*44}")
    print(f"  {'Sharpe':22s} {fmt(m.sharpe_ratio, '>+10.2f')} {fmt(mb.sharpe_ratio, '>+10.2f')}")
    print(f"  {'Compound Return':22s} {fmt(m.total_return_pct, '>+9.1f')}% {fmt(mb.total_return_pct, '>+9.1f')}%")
    print(f"  {'Max DD':22s} {fmt(m.max_drawdown_pct, '>+9.1f')}% {fmt(mb.max_drawdown_pct, '>+9.1f')}%")
    print(f"  {'Win Rate':22s} {m.win_rate_pct:>9.1f}% {mb.win_rate_pct:>9.1f}%")
    print(f"  {'Profit Factor':22s} {m.profit_factor:>10.2f} {mb.profit_factor:>10.2f}")
    print(f"  {'Trades':22s} {m.total_trades:>10d} {mb.total_trades:>10d}")

    # ── Walk-Forward: Binance ─────────────────────────────────────
    print_separator("WALK-FORWARD — BINANCE (7 splits, OOS)")

    wf_b = walk_forward(df_binance, strategy, stop_pct, target_pct, max_hold_bars)

    wf_b_sharpes = []
    wf_b_positive = 0
    for wr in wf_b:
        wf_b_sharpes.append(wr["sharpe"])
        if wr["profitable"]:
            wf_b_positive += 1
        status = "OK" if wr["profitable"] else "!!"
        print(f"  Split {wr['split']}: {wr['start']} -> {wr['end']}  "
              f"trades={wr['trades']:3d}  return={fmt(wr['return_pct'], '+.1f')}%  "
              f"sharpe={fmt(wr['sharpe'], '+.2f')}  dd={fmt(wr['max_dd'], '+.1f')}%  {status}")

    print()
    print(f"  OOS Profitable:  {wf_b_positive}/{len(wf_b)} splits")
    print(f"  Mean OOS Sharpe: {fmt(np.mean(wf_b_sharpes), '+.2f')}")
    print(f"  Total OOS Return: {fmt(sum(wr['return_pct'] for wr in wf_b), '+.1f')}%")

    # ── SMA200 Filter Impact ──────────────────────────────────────
    print_separator("SMA200 FILTER IMPACT (v1.3.0 validation)")

    # Run without SMA200
    strategy_no_sma = SpringReversal(params={"sma200_filter": False})
    engine_ns = BacktestEngine(
        initial_capital=10_000,
        commission=strategy.params["commission"],
        slippage=0.0005,
        use_lows_for_stops=True,
    )
    result_ns = engine_ns.run(
        df_okx, strategy_no_sma, symbol="BTC/USDT",
        stop_loss_pct=stop_pct, take_profit_pct=target_pct,
        max_hold_bars=max_hold_bars,
    )

    print()
    print(f"  {'Metric':22s} {'With SMA200':>12s} {'No SMA200':>12s} {'Delta':>12s}")
    print(f"  {'-'*60}")
    print(f"  {'Trades':22s} {m.total_trades:>12d} {result_ns.metrics.total_trades:>12d} "
          f"{result_ns.metrics.total_trades - m.total_trades:>+12d}")
    print(f"  {'Sharpe':22s} {fmt(m.sharpe_ratio, '>+12.2f')} "
          f"{fmt(result_ns.metrics.sharpe_ratio, '>+12.2f')} "
          f"{fmt(result_ns.metrics.sharpe_ratio - m.sharpe_ratio, '>+12.2f')}")
    print(f"  {'Compound Return':22s} {fmt(m.total_return_pct, '>+11.1f')}% "
          f"{fmt(result_ns.metrics.total_return_pct, '>+11.1f')}% "
          f"{fmt(result_ns.metrics.total_return_pct - m.total_return_pct, '>+11.1f')}%")
    print(f"  {'Max DD':22s} {fmt(m.max_drawdown_pct, '>+11.1f')}% "
          f"{fmt(result_ns.metrics.max_drawdown_pct, '>+11.1f')}% "
          f"{fmt(result_ns.metrics.max_drawdown_pct - m.max_drawdown_pct, '>+11.1f')}%")
    print(f"  {'Win Rate':22s} {m.win_rate_pct:>11.1f}% "
          f"{result_ns.metrics.win_rate_pct:>11.1f}% "
          f"{result_ns.metrics.win_rate_pct - m.win_rate_pct:>+11.1f}%")
    print(f"  {'Profit Factor':22s} {m.profit_factor:>12.2f} "
          f"{result_ns.metrics.profit_factor:>12.2f} "
          f"{result_ns.metrics.profit_factor - m.profit_factor:>+12.2f}")

    # ── Comparison with unfiltered baseline ────────────────────────
    print_separator("COMPARISON: FILTERED vs UNFILTERED BASELINE")

    # Baseline: no SMA200, no BB filter, original exits
    strategy_base = SpringReversal(params={
        "sma200_filter": False,
        "bb_filter": False,
    })
    engine_base = BacktestEngine(
        initial_capital=10_000,
        commission=strategy.params["commission"],
        slippage=0.0005,
        use_lows_for_stops=True,
    )
    result_base = engine_base.run(
        df_okx, strategy_base, symbol="BTC/USDT",
        stop_loss_pct=3.0, take_profit_pct=5.0, max_hold_bars=24,
    )

    print()
    print(f"  {'Metric':22s} {'Baseline':>12s} {'Filtered v1.3':>14s} {'Improvement':>14s}")
    print(f"  {'-'*64}")
    print(f"  {'Trades':22s} {result_base.metrics.total_trades:>12d} {m.total_trades:>14d} "
          f"{m.total_trades - result_base.metrics.total_trades:>+14d}")
    print(f"  {'Sharpe':22s} {fmt(result_base.metrics.sharpe_ratio, '>+12.2f')} "
          f"{fmt(m.sharpe_ratio, '>+14.2f')} "
          f"{fmt(m.sharpe_ratio - result_base.metrics.sharpe_ratio, '>+14.2f')}")
    print(f"  {'Compound Return':22s} {fmt(result_base.metrics.total_return_pct, '>+11.1f')}% "
          f"{fmt(m.total_return_pct, '>+13.1f')}% "
          f"{fmt(m.total_return_pct - result_base.metrics.total_return_pct, '>+13.1f')}%")
    print(f"  {'Max DD':22s} {fmt(result_base.metrics.max_drawdown_pct, '>+11.1f')}% "
          f"{fmt(m.max_drawdown_pct, '>+13.1f')}% "
          f"{fmt(m.max_drawdown_pct - result_base.metrics.max_drawdown_pct, '>+13.1f')}%")
    print(f"  {'Win Rate':22s} {result_base.metrics.win_rate_pct:>11.1f}% "
          f"{m.win_rate_pct:>13.1f}% "
          f"{m.win_rate_pct - result_base.metrics.win_rate_pct:>+13.1f}%")
    print(f"  {'Profit Factor':22s} {result_base.metrics.profit_factor:>12.2f} "
          f"{m.profit_factor:>14.2f} "
          f"{m.profit_factor - result_base.metrics.profit_factor:>+14.2f}")

    print()
    print("=" * 70)
    print("  DONE — Spring Reversal v1.3.0 definitive backtest complete")
    print("=" * 70)


if __name__ == "__main__":
    main()
