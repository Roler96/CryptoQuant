"""
Spring Reversal — Exit Optimization for Best Filter
===================================================
Tests the SMA200 + BB %B 0.2-0.6 filter with various exit parameters
to find the optimal configuration. Also validates the "lower the target"
pattern since 98.2% of time-exits were profitable at some point.
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


def compute_metrics(trades):
    if not trades:
        return {}
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
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
    
    max_consec = 0
    consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
    downside = [p for p in pnls if p < 0]
    sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if downside and len(pnls) > 1 and np.std(downside) > 0 else 0
    
    return {
        "trades": len(trades),
        "sum": sum(pnls),
        "compound": compound_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": len(wins) / len(pnls) * 100,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "pf": sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf'),
        "max_consec": max_consec,
    }


def walk_forward_analysis(df, signal_series, params, n_splits=6):
    n = len(df)
    slot = len(df) // (n_splits + 2)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        split_sig = signal_series.iloc[start:end]
        
        t = regime_backtest(split_df, split_sig, {}, **params)
        
        if t:
            p = [x["pnl_pct"] for x in t]
            ss = sum(p)
            ssh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
        else:
            ss = 0
            ssh = 0
        
        results.append({
            "split": s + 1,
            "start": split_df.index[0],
            "end": split_df.index[-1],
            "trades": len(t) if t else 0,
            "sum": ss,
            "sharpe": ssh,
        })
    
    return results


def main():
    print("=" * 70)
    print("SPRING REVERSAL — EXIT OPTIMIZATION (SMA200 + BB 0.2-0.6)")
    print("=" * 70)
    
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    print(f"\nOKX: {len(df_okx)} bars")
    
    # Compute indicators
    df = df_okx.copy()
    df["sma200"] = sma(df["close"], 200)
    adx_df = adx_func(df, 14)
    df["adx"] = adx_df["adx"]
    df["pdi"] = adx_df["pdi"]
    df["mdi"] = adx_df["mdi"]
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]
    
    # Generate signals
    base_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    best_sig = base_sig & (df["close"] > df["sma200"]) & (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)
    
    print(f"Base signals: {base_sig.sum()}")
    print(f"Filtered signals: {best_sig.sum()}")
    
    # ========================================================================
    # GRID SEARCH: Stop × Target × Hold
    # ========================================================================
    print("\n" + "=" * 70)
    print("GRID SEARCH: Stop × Target × Hold")
    print("=" * 70)
    
    stops = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    targets = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]
    holds = [8, 12, 16, 20, 24, 32]
    
    results = []
    for sl in stops:
        for tp in targets:
            for hh in holds:
                params = {
                    "stop_pct": sl,
                    "target_pct": tp,
                    "max_hold": hh,
                    "commission": 0.0005,
                    "slippage": 0.0005,
                }
                t = regime_backtest(df, best_sig, {}, **params)
                if t:
                    m = compute_metrics(t)
                    results.append({
                        "stop": sl,
                        "target": tp,
                        "hold": hh,
                        **m,
                    })
    
    # Sort by Sharpe
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    
    print(f"\nTop 20 by Sharpe:")
    print(f"{'Rank':>4s} {'Stop':>6s} {'Target':>7s} {'Hold':>6s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s}")
    print("-" * 85)
    for i, r in enumerate(results[:20], 1):
        print(f"{i:>4d} {r['stop']:>5.1f}% {r['target']:>6.1f}% {r['hold']:>5d}h {r['trades']:>7d} {r['sum']:>+7.1f}% {r['sharpe']:>+7.2f} {r['win_rate']:>5.1f}% {r['pf']:>5.2f} {r['max_dd']:>+7.1f}%")
    
    # Also sort by PF (for robustness)
    results.sort(key=lambda x: x["pf"], reverse=True)
    print(f"\nTop 20 by Profit Factor:")
    print(f"{'Rank':>4s} {'Stop':>6s} {'Target':>7s} {'Hold':>6s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s}")
    print("-" * 85)
    for i, r in enumerate(results[:20], 1):
        print(f"{i:>4d} {r['stop']:>5.1f}% {r['target']:>6.1f}% {r['hold']:>5d}h {r['trades']:>7d} {r['sum']:>+7.1f}% {r['sharpe']:>+7.2f} {r['win_rate']:>5.1f}% {r['pf']:>5.2f} {r['max_dd']:>+7.1f}%")
    
    # ========================================================================
    # BEST CONFIG: Detailed Backtest
    # ========================================================================
    # Pick the best by combined Sharpe + PF + reasonable trades
    # Filter: Sharpe > 2.0, PF > 2.0, trades > 30
    candidates = [r for r in results if r["sharpe"] > 2.0 and r["pf"] > 2.0 and r["trades"] > 30]
    if not candidates:
        candidates = [r for r in results if r["sharpe"] > 1.5 and r["trades"] > 30]
    
    best = candidates[0] if candidates else results[0]
    
    print("\n" + "=" * 70)
    print(f"BEST CONFIGURATION: stop={best['stop']}%, target={best['target']}%, hold={best['hold']}h")
    print("=" * 70)
    
    best_params = {
        "stop_pct": best["stop"],
        "target_pct": best["target"],
        "max_hold": best["hold"],
        "commission": 0.0005,
        "slippage": 0.0005,
    }
    
    # Full backtest with regime tagging
    regime_data = {
        "above_sma200": (df["close"] > df["sma200"]).values,
        "adx": df["adx"].values,
        "pdi": df["pdi"].values,
        "mdi": df["mdi"].values,
        "rsi14": rsi(df["close"], 14).values,
        "bb_pct_b": df["bb_pct_b"].values,
        "dd48": pct_change_rolling(df["close"], 48).values,
    }
    
    trades = regime_backtest(df, best_sig, regime_data, **best_params)
    m = compute_metrics(trades)
    
    print(f"\n  FULL BACKTEST RESULTS (OKX BTC/USDT 1h, 2019-2026)")
    print(f"  {'='*50}")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {m['trades']}")
    print(f"  Compound Return:    {m['compound']:+.1f}%")
    print(f"  Linear Sum:         {m['sum']:+.1f}%")
    print(f"  Sharpe Ratio:       {m['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {m['sortino']:+.2f}")
    print(f"  Max Drawdown:       {m['max_dd']:+.1f}%")
    print(f"  Win Rate:           {m['win_rate']:.1f}%")
    print(f"  Avg Win:            {m['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {m['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {m['pf']:.2f}")
    print(f"  Max Consec Losses:  {m['max_consec']}")
    
    exit_counts = Counter(t["exit_reason"] for t in trades)
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t["exit_reason"] == reason]
        if subset:
            sp = [t["pnl_pct"] for t in subset]
            print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(trades)*100:5.1f}%)  avg={np.mean(sp):+.2f}%  total={sum(sp):+.1f}%")
    
    # MFE/MAE
    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    print(f"\n  Max Favorable Excursion (MFE):")
    print(f"    Mean:   {np.mean(mfes):+.2f}%")
    print(f"    Median: {np.median(mfes):+.2f}%")
    print(f"    Max:    {np.max(mfes):+.2f}%")
    print(f"\n  Max Adverse Excursion (MAE):")
    print(f"    Mean:   {np.mean(maes):+.2f}%")
    print(f"    Median: {np.median(maes):+.2f}%")
    
    time_ex = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_ex:
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"\n  Time-exit trades profitable at some point: {profitable_time}/{len(time_ex)} ({profitable_time/len(time_ex)*100:.1f}%)")
    
    # ========================================================================
    # WALK-FORWARD
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"WALK-FORWARD VALIDATION (6 splits)")
    print(f"{'='*55}")
    
    wf = walk_forward_analysis(df, best_sig, best_params)
    wf_positive = 0
    total_wf_sum = 0
    all_sharpes = []
    for r in wf:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        total_wf_sum += r["sum"]
        all_sharpes.append(r["sharpe"])
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  OOS Profitable: {wf_positive}/{len(wf)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # ========================================================================
    # PARAMETER SENSITIVITY
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"PARAMETER SENSITIVITY (around best)")
    print(f"{'='*55}")
    
    # Hold sweep around best
    print(f"\n--- Hold Time Sweep (stop={best['stop']}%, target={best['target']}%) ---")
    print(f"{'Hold':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s}")
    print("-" * 55)
    for hh in [6, 8, 10, 12, 16, 20, 24, 32, 48]:
        params = {**best_params, "max_hold": hh}
        t = regime_backtest(df, best_sig, {}, **params)
        if t:
            m2 = compute_metrics(t)
            print(f"{hh:>7d}h {m2['trades']:>7d} {m2['sum']:>+7.1f}% {m2['sharpe']:>+7.2f} {m2['win_rate']:>5.1f}% {m2['pf']:>5.2f} {m2['max_dd']:>+7.1f}%")
    
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
    best_sig_b = sig_b & (df_b["close"] > df_b["sma200"]) & (df_b["bb_pct_b"] >= 0.2) & (df_b["bb_pct_b"] < 0.6)
    
    trades_b = regime_backtest(df_b, best_sig_b, {}, **best_params)
    if trades_b:
        m_b = compute_metrics(trades_b)
        print(f"\n  Total Trades:       {m_b['trades']}")
        print(f"  Linear Sum:         {m_b['sum']:+.1f}%")
        print(f"  Sharpe Ratio:       {m_b['sharpe']:+.2f}")
        print(f"  Win Rate:           {m_b['win_rate']:.1f}%")
        print(f"  Profit Factor:      {m_b['pf']:.2f}")
        print(f"  Max Drawdown:       {m_b['max_dd']:+.1f}%")
        
        print(f"\n  Cross-Exchange Comparison:")
        print(f"  {'Metric':20s} {'OKX':>10s} {'Binance':>10s}")
        print(f"  {'-'*42}")
        for label, okx_val, bin_val in [
            ("Sharpe", m["sharpe"], m_b["sharpe"]),
            ("Return (sum)", m["sum"], m_b["sum"]),
            ("Max DD", m["max_dd"], m_b["max_dd"]),
            ("Win Rate", m["win_rate"], m_b["win_rate"]),
            ("Profit Factor", m["pf"], m_b["pf"]),
            ("Trades", m["trades"], m_b["trades"]),
        ]:
            if label in ("Return (sum)", "Max DD"):
                print(f"  {label:20s} {okx_val:>+9.1f}% {bin_val:>+9.1f}%")
            elif label == "Win Rate":
                print(f"  {label:20s} {okx_val:>9.1f}% {bin_val:>9.1f}%")
            elif label == "Trades":
                print(f"  {label:20s} {okx_val:>10d} {bin_val:>10d}")
            else:
                print(f"  {label:20s} {okx_val:>+10.2f} {bin_val:>+10.2f}")
        
        # Binance WF
        print(f"\n  Binance Walk-Forward:")
        wf_b = walk_forward_analysis(df_b, best_sig_b, best_params)
        wf_pos = 0
        for r in wf_b:
            status = "✅" if r["sum"] > 0 else "❌"
            if r["sum"] > 0:
                wf_pos += 1
            print(f"    Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
        print(f"    OOS Profitable: {wf_pos}/{len(wf_b)} splits")
        print(f"    Mean OOS Sharpe: {np.mean([x['sharpe'] for x in wf_b]):+.2f}")
    
    # ========================================================================
    # COMPARISON: BB 0.2-0.6 + SMA200 vs BB 0.2-0.6 no SMA200
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"FILTER COMPARISON: SMA200 vs no SMA200 (BB 0.2-0.6 only)")
    print(f"{'='*55}")
    
    bb_only_sig = base_sig & (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)
    trades_bb = regime_backtest(df, bb_only_sig, {}, **best_params)
    if trades_bb:
        m_bb = compute_metrics(trades_bb)
        print(f"\n  BB 0.2-0.6 only (no SMA200):")
        print(f"    Trades: {m_bb['trades']}, Sum: {m_bb['sum']:+.1f}%, Sharpe: {m_bb['sharpe']:+.2f}, WR: {m_bb['win_rate']:.1f}%, PF: {m_bb['pf']:.2f}, MaxDD: {m_bb['max_dd']:+.1f}%")
    
    print(f"\n  BB 0.2-0.6 + SMA200:")
    print(f"    Trades: {m['trades']}, Sum: {m['sum']:+.1f}%, Sharpe: {m['sharpe']:+.2f}, WR: {m['win_rate']:.1f}%, PF: {m['pf']:.2f}, MaxDD: {m['max_dd']:+.1f}%")
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
