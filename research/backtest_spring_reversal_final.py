"""
Spring Reversal — Final Best Configuration
===========================================

Best from Phase 3: BB 0.2-0.6 + SMA200 filter
  stop=3.0%, target=2.5%, hold=24h → Sharpe 1.43, sum +24.5%, 74 trades, Max DD -6.2%

This script produces the final detailed report.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, adx as adx_func,
    pct_change_rolling, rsi, bollinger_bands
)

from backtest_spring_reversal import spring_signal, regime_backtest


def main():
    print("=" * 70)
    print("SPRING REVERSAL — FINAL BEST CONFIGURATION")
    print("=" * 70)
    
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    print(f"\nOKX: {len(df_okx)} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance: {len(df_binance)} bars, {df_binance.index[0]} to {df_binance.index[-1]}")
    
    # Compute indicators
    df = df_okx.copy()
    df["sma200"] = sma(df["close"], 200)
    df["sma50"] = sma(df["close"], 50)
    
    adx_df = adx_func(df, 14)
    df["adx"] = adx_df["adx"]
    df["pdi"] = adx_df["pdi"]
    df["mdi"] = adx_df["mdi"]
    
    df["atr14"] = atr_func(df, 14)
    df["median_atr200"] = df["atr14"].rolling(200).median()
    df["vol_ratio"] = df["atr14"] / df["median_atr200"]
    
    df["rsi14"] = rsi(df["close"], 14)
    df["dd48"] = pct_change_rolling(df["close"], 48)
    
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]
    
    # ========================================================================
    # BEST CONFIGURATION
    # ========================================================================
    
    base_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    bb_filter = (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)
    sma200_filter = df["close"] > df["sma200"]
    
    best_sig = base_sig & bb_filter & sma200_filter
    
    best_params = {
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "max_hold": 24,
        "commission": 0.0005,
        "slippage": 0.0005,
    }
    
    print(f"\nBest Configuration:")
    print(f"  Signal: Spring Reversal (lookback=20, vol_mult=1.5, close_pct=0.5)")
    print(f"  Filters: BB %B 0.2-0.6 + SMA200")
    print(f"  Exits: stop=3.0%, target=2.5%, hold=24h")
    print(f"  Signal count: {best_sig.sum()}")
    
    # Regime data
    regime_data = {
        "above_sma200": (df["close"] > df["sma200"]).values,
        "adx": df["adx"].values,
        "pdi": df["pdi"].values,
        "mdi": df["mdi"].values,
        "vol_ratio": df["vol_ratio"].values,
        "rsi14": df["rsi14"].values,
        "dd48": df["dd48"].values,
        "bb_pct_b": df["bb_pct_b"].values,
    }
    
    trades = regime_backtest(df, best_sig, regime_data, **best_params)
    
    if not trades:
        print("ERROR: No trades!")
        return
    
    pnls = [t["pnl_pct"] for t in trades]
    total_sum = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) * 100
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 else 0
    
    downside = [p for p in pnls if p < 0]
    sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if downside and len(pnls) > 1 else 0
    
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    max_consec = 0
    consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    
    compound = 1.0
    for p in pnls:
        compound *= (1 + p / 100)
    compound_return = (compound - 1) * 100
    
    equity = [10000]
    for p in pnls:
        equity.append(equity[-1] * (1 + p / 100))
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    max_dd = dd.min()
    
    years = (df.index[-1] - df.index[0]).days / 365.25
    annualized = ((1 + compound_return / 100) ** (1 / years) - 1) * 100
    
    exit_counts = Counter(t["exit_reason"] for t in trades)
    
    print(f"\n{'='*55}")
    print(f"FULL BACKTEST RESULTS (OKX BTC/USDT 1h, 2019-2026)")
    print(f"{'='*55}")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {len(trades)}")
    print(f"  Compound Return:    {compound_return:+.1f}%")
    print(f"  Annualized Return:  {annualized:+.1f}%")
    print(f"  Linear Sum:         {total_sum:+.1f}%")
    print(f"  Sharpe Ratio:       {sharpe:+.2f}")
    print(f"  Sortino Ratio:      {sortino:+.2f}")
    print(f"  Max Drawdown:       {max_dd:+.1f}%")
    print(f"  Win Rate:           {win_rate:.1f}%")
    print(f"  Avg Win:            {avg_win:+.2f}%")
    print(f"  Avg Loss:           {avg_loss:+.2f}%")
    print(f"  Profit Factor:      {pf:.2f}")
    print(f"  Max Consec Losses:  {max_consec}")
    
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t["exit_reason"] == reason]
        if subset:
            sp = [t["pnl_pct"] for t in subset]
            print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(trades)*100:5.1f}%)  avg={np.mean(sp):+.2f}%  total={sum(sp):+.1f}%")
    
    # ========================================================================
    # WALK-FORWARD
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"WALK-FORWARD VALIDATION (6 splits, OOS)")
    print(f"{'='*55}")
    
    n = len(df)
    slot = len(df) // 8
    n_splits = 6
    
    wf_positive = 0
    total_wf_sum = 0
    all_wf_sharpes = []
    
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_sig = best_sig.iloc[start:end]
        split_df = df.iloc[start:end]
        t = regime_backtest(split_df, split_sig, {}, **best_params)
        
        if t:
            p = [x["pnl_pct"] for x in t]
            ss = sum(p)
            ssh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
        else:
            ss = 0
            ssh = 0
        
        if ss > 0:
            wf_positive += 1
        total_wf_sum += ss
        all_wf_sharpes.append(ssh)
        status = "✅" if ss > 0 else "❌"
        print(f"  Split {s+1}: {split_df.index[0].strftime('%Y-%m')}→{split_df.index[-1].strftime('%Y-%m')}  trades={len(t):3d}  sum={ss:+.1f}%  sharpe={ssh:+.2f}  {status}")
    
    print(f"  OOS Profitable: {wf_positive}/{n_splits} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_wf_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # ========================================================================
    # REGIME ANALYSIS
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"REGIME ANALYSIS (filtered trades)")
    print(f"{'='*55}")
    
    # All trades are above SMA200 by filter, so skip that
    
    # PDI/MDI
    pdi_above = [t for t in trades if t.get("pdi", 0) > t.get("mdi", 0)]
    pdi_below = [t for t in trades if t.get("pdi", 0) <= t.get("mdi", 0)]
    for label, subset in [("PDI > MDI", pdi_above), ("PDI <= MDI", pdi_below)]:
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:20s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # ADX
    for threshold, label in [(25, "ADX > 25 (strong)"), (25, "ADX <= 25 (weak)")]:
        if ">" in label:
            subset = [t for t in trades if t.get("adx", 0) > threshold]
        else:
            subset = [t for t in trades if t.get("adx", 0) <= threshold]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # RSI
    for low, high, label in [
        (0, 40, "RSI < 40"),
        (40, 50, "RSI 40-50"),
        (50, 60, "RSI 50-60"),
        (60, 100, "RSI >= 60"),
    ]:
        subset = [t for t in trades if low <= t.get("rsi14", 50) < high]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # 48h price change
    for low, high, label in [
        (-100, -5, "Crash (<-5%)"),
        (-5, -2, "Drop (-5 to -2%)"),
        (-2, 0, "Flat (-2 to 0%)"),
        (0, 2, "Mild up (0 to 2%)"),
        (2, 5, "Rally (2 to 5%)"),
        (5, 100, "Strong rally (>5%)"),
    ]:
        subset = [t for t in trades if low <= t.get("dd48", 0) < high]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # ========================================================================
    # MFE/MAE
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"MFE/MAE ANALYSIS")
    print(f"{'='*55}")
    
    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    
    print(f"  Max Favorable Excursion (MFE):")
    print(f"    Mean:   {np.mean(mfes):+.2f}%")
    print(f"    Median: {np.median(mfes):+.2f}%")
    print(f"    Max:    {np.max(mfes):+.2f}%")
    
    print(f"\n  Max Adverse Excursion (MAE):")
    print(f"    Mean:   {np.mean(maes):+.2f}%")
    print(f"    Median: {np.median(maes):+.2f}%")
    
    # MFE by exit reason
    print(f"\n  MFE by Exit Reason:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        subset = [t["mfe_pct"] for t in trades if t["exit_reason"] == reason]
        if subset:
            print(f"    {reason:15s}: mean={np.mean(subset):+.2f}%  median={np.median(subset):+.2f}%")
    
    time_ex = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_ex:
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"\n  Time-exit trades profitable at some point: {profitable_time}/{len(time_ex)} ({profitable_time/len(time_ex)*100:.1f}%)")
    
    # ========================================================================
    # BINANCE CROSS-VALIDATION
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"BINANCE CROSS-VALIDATION")
    print(f"{'='*55}")
    
    df_b = df_binance.copy()
    df_b["sma200"] = sma(df_b["close"], 200)
    bb_b = bollinger_bands(df_b, 20, 2.0)
    df_b["bb_pct_b"] = bb_b["pct_b"]
    
    sig_b = spring_signal(df_b, lookback=20, vol_mult=1.5, close_pct=0.5)
    sig_b = sig_b & (df_b["bb_pct_b"] >= 0.2) & (df_b["bb_pct_b"] < 0.6) & (df_b["close"] > df_b["sma200"])
    
    trades_b = regime_backtest(df_b, sig_b, {}, **best_params)
    
    if trades_b:
        bp = [t["pnl_pct"] for t in trades_b]
        bs = sum(bp)
        bsh = np.mean(bp) / np.std(bp) * np.sqrt(len(bp)) if len(bp) > 1 else 0
        bwr = sum(1 for x in bp if x > 0) / len(bp) * 100
        bw = [x for x in bp if x > 0]
        bl = [x for x in bp if x <= 0]
        bpf = sum(bw) / abs(sum(bl)) if bl and sum(bl) != 0 else 0
        beq = [10000]
        for x in bp:
            beq.append(beq[-1] * (1 + x / 100))
        beq = np.array(beq)
        bdd = (beq - np.maximum.accumulate(beq)).min() / np.maximum.accumulate(beq).max() * 100
        
        print(f"  Total Trades:       {len(trades_b)}")
        print(f"  Linear Sum:         {bs:+.1f}%")
        print(f"  Sharpe Ratio:       {bsh:+.2f}")
        print(f"  Win Rate:           {bwr:.1f}%")
        print(f"  Profit Factor:      {bpf:.2f}")
        print(f"  Max Drawdown:       {bdd:+.1f}%")
        
        print(f"\n  Cross-Exchange Comparison:")
        print(f"  {'Metric':20s} {'OKX':>10s} {'Binance':>10s}")
        print(f"  {'-'*42}")
        print(f"  {'Sharpe':20s} {sharpe:>+10.2f} {bsh:>+10.2f}")
        print(f"  {'Return (sum)':20s} {total_sum:>+10.1f}% {bs:>+9.1f}%")
        print(f"  {'Max DD':20s} {max_dd:>+10.1f}% {bdd:>+9.1f}%")
        print(f"  {'Win Rate':20s} {win_rate:>10.1f}% {bwr:>9.1f}%")
        print(f"  {'Profit Factor':20s} {pf:>10.2f} {bpf:>9.2f}")
        print(f"  {'Trades':20s} {len(trades):>10d} {len(trades_b):>9d}")
    
    # ========================================================================
    # BASELINE COMPARISON
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"COMPARISON WITH BASELINE (unfiltered Spring)")
    print(f"{'='*55}")
    
    baseline_metrics = {
        "Sharpe": -0.71,
        "Return (sum)": -43.2,
        "Max DD": -55.0,
        "Win Rate": 48.1,
        "Profit Factor": 0.93,
        "Trades": 543,
    }
    
    best_metrics = {
        "Sharpe": sharpe,
        "Return (sum)": total_sum,
        "Max DD": max_dd,
        "Win Rate": win_rate,
        "Profit Factor": pf,
        "Trades": len(trades),
    }
    
    print(f"\n  {'Metric':20s} {'Baseline':>12s} {'BB+SMA200':>12s} {'Delta':>12s}")
    print(f"  {'-'*58}")
    for key in ["Sharpe", "Return (sum)", "Max DD", "Win Rate", "Profit Factor", "Trades"]:
        b = baseline_metrics[key]
        c = best_metrics[key]
        d = c - b
        if key == "Return (sum)" or key == "Max DD":
            print(f"  {key:20s} {b:>+11.1f}% {c:>+11.1f}% {d:>+11.1f}%")
        elif key == "Win Rate":
            print(f"  {key:20s} {b:>11.1f}% {c:>11.1f}% {d:>+11.1f}%")
        elif key == "Trades":
            print(f"  {key:20s} {b:>12d} {c:>12d} {d:>+12d}")
        else:
            print(f"  {key:20s} {b:>+11.2f} {c:>+11.2f} {d:>+11.2f}")
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
