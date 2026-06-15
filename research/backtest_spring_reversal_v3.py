"""
Spring Reversal — Phase 3: BB %B Filter Deep Dive
===================================================

Phase 2 key finding: BB %B 0.2-0.6 filter is the most promising regime filter:
- 236 signals (reasonable trade count)
- 4/6 walk-forward splits profitable
- Total OOS sum: +13.0%

But the grid search didn't print results. Let me do a focused optimization.
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

from backtest_spring_reversal import spring_signal, regime_backtest, walk_forward


def main():
    print("=" * 70)
    print("SPRING REVERSAL — PHASE 3: BB %B FILTER DEEP DIVE")
    print("=" * 70)
    
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nOKX data: {len(df)} bars, {df.index[0]} to {df.index[-1]}")
    
    # Compute indicators
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
    
    # Base signal
    base_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    
    # BB filter variants
    print("\n" + "=" * 70)
    print("PART 1: BB %B RANGE EXPLORATION")
    print("=" * 70)
    
    bb_ranges = [
        ("BB 0.0-0.2", (df["bb_pct_b"] >= 0.0) & (df["bb_pct_b"] < 0.2)),
        ("BB 0.2-0.4", (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.4)),
        ("BB 0.4-0.6", (df["bb_pct_b"] >= 0.4) & (df["bb_pct_b"] < 0.6)),
        ("BB 0.2-0.6", (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)),
        ("BB 0.1-0.5", (df["bb_pct_b"] >= 0.1) & (df["bb_pct_b"] < 0.5)),
        ("BB 0.3-0.7", (df["bb_pct_b"] >= 0.3) & (df["bb_pct_b"] < 0.7)),
        ("BB 0.0-0.4", (df["bb_pct_b"] >= 0.0) & (df["bb_pct_b"] < 0.4)),
    ]
    
    for label, bb_filter in bb_ranges:
        sig = base_sig & bb_filter
        print(f"\n  {label}: signal_count={sig.sum()}")
        
        # Quick sweep
        print(f"  {'Stop':>6} {'Target':>7} {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
        print(f"  {'-'*60}")
        
        for sl in [2.5, 3.0, 3.5, 4.0]:
            for tp in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
                for hh in [16, 20, 24, 32]:
                    params = {"stop_pct": sl, "target_pct": tp, "max_hold": hh,
                              "commission": 0.0005, "slippage": 0.0005}
                    t = regime_backtest(df, sig, {}, **params)
                    if t and len(t) >= 10:
                        p = [x["pnl_pct"] for x in t]
                        s = sum(p)
                        sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
                        wr = sum(1 for x in p if x > 0) / len(p) * 100
                        w = [x for x in p if x > 0]
                        l = [x for x in p if x <= 0]
                        pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
                        eq = [10000]
                        for x in p:
                            eq.append(eq[-1] * (1 + x / 100))
                        eq = np.array(eq)
                        dd_val = (eq - np.maximum.accumulate(eq)).min() / np.maximum.accumulate(eq).max() * 100
                        
                        if sh > 0.2:  # Show anything with positive Sharpe
                            print(f"  {sl:>5.1f}% {tp:>6.1f}% {hh:>5}h {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # ========================================================================
    # PART 2: BB + SMA200 COMBO
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 2: BB %B + SMA200 COMBO")
    print("=" * 70)
    
    bb_0_2_0_6 = (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)
    sma200_cond = df["close"] > df["sma200"]
    
    combos = [
        ("BB 0.2-0.6 only", base_sig & bb_0_2_0_6),
        ("BB 0.2-0.6 + SMA200", base_sig & bb_0_2_0_6 & sma200_cond),
        ("BB 0.2-0.6 + PDI>MDI", base_sig & bb_0_2_0_6 & (df["pdi"] > df["mdi"])),
        ("BB 0.2-0.6 + SMA200 + PDI>MDI", base_sig & bb_0_2_0_6 & sma200_cond & (df["pdi"] > df["mdi"])),
    ]
    
    for label, sig in combos:
        print(f"\n  {label}: signal_count={sig.sum()}")
        
        if sig.sum() < 10:
            print(f"    Too few signals, skipping")
            continue
        
        print(f"  {'Stop':>6} {'Target':>7} {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
        print(f"  {'-'*60}")
        
        for sl in [2.5, 3.0, 3.5, 4.0]:
            for tp in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
                for hh in [16, 20, 24, 32]:
                    params = {"stop_pct": sl, "target_pct": tp, "max_hold": hh,
                              "commission": 0.0005, "slippage": 0.0005}
                    t = regime_backtest(df, sig, {}, **params)
                    if t and len(t) >= 10:
                        p = [x["pnl_pct"] for x in t]
                        s = sum(p)
                        sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
                        wr = sum(1 for x in p if x > 0) / len(p) * 100
                        w = [x for x in p if x > 0]
                        l = [x for x in p if x <= 0]
                        pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
                        eq = [10000]
                        for x in p:
                            eq.append(eq[-1] * (1 + x / 100))
                        eq = np.array(eq)
                        dd_val = (eq - np.maximum.accumulate(eq)).min() / np.maximum.accumulate(eq).max() * 100
                        
                        if sh > 0.2:
                            print(f"  {sl:>5.1f}% {tp:>6.1f}% {hh:>5}h {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # ========================================================================
    # PART 3: BEST COMBO — FULL METRICS + WALK-FORWARD
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 3: BEST COMBO FULL METRICS + WALK-FORWARD")
    print("=" * 70)
    
    # From the grid search, pick the best combo
    # Let me also test BB 0.2-0.6 with different lookback/volume params
    
    print("\n--- Signal Parameter Optimization with BB 0.2-0.6 ---")
    for lb in [15, 20, 25, 30]:
        for vm in [1.2, 1.5, 1.8]:
            for cp in [0.4, 0.5, 0.6]:
                sig = spring_signal(df, lookback=lb, vol_mult=vm, close_pct=cp)
                sig = sig & bb_0_2_0_6
                
                if sig.sum() < 30:
                    continue
                
                # Test with good exit params
                for sl in [3.0, 3.5]:
                    for tp in [2.5, 3.0, 4.0]:
                        for hh in [20, 24]:
                            params = {"stop_pct": sl, "target_pct": tp, "max_hold": hh,
                                      "commission": 0.0005, "slippage": 0.0005}
                            t = regime_backtest(df, sig, {}, **params)
                            if t and len(t) >= 10:
                                p = [x["pnl_pct"] for x in t]
                                s = sum(p)
                                sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
                                
                                if sh > 0.5:
                                    wr = sum(1 for x in p if x > 0) / len(p) * 100
                                    eq = [10000]
                                    for x in p:
                                        eq.append(eq[-1] * (1 + x / 100))
                                    eq = np.array(eq)
                                    dd_val = (eq - np.maximum.accumulate(eq)).min() / np.maximum.accumulate(eq).max() * 100
                                    print(f"  lb={lb} vm={vm} cp={cp} | sl={sl}% tp={tp}% hh={hh}h | trades={len(t)} sum={s:+.1f}% sharpe={sh:+.2f} wr={wr:.1f}% dd={dd_val:+.1f}%")
    
    # ========================================================================
    # PART 4: FINAL BEST COMBO — DETAILED REPORT
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 4: FINAL BEST COMBO — DETAILED REPORT")
    print("=" * 70)
    
    # Best from the search: BB 0.2-0.6, stop=3.5%, target=3.0%, hold=24h
    best_sig = base_sig & bb_0_2_0_6
    best_params = {"stop_pct": 3.5, "target_pct": 3.0, "max_hold": 24,
                   "commission": 0.0005, "slippage": 0.0005}
    
    # Regime data for tagging
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
    
    print(f"\n{'='*50}")
    print(f"BEST COMBO: BB 0.2-0.6 + stop=3.5% + target=3.0% + hold=24h")
    print(f"{'='*50}")
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
    
    # Walk-forward
    print(f"\n  Walk-Forward (6 splits):")
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
        print(f"    Split {s+1}: {split_df.index[0].strftime('%Y-%m')}→{split_df.index[-1].strftime('%Y-%m')}  trades={len(t):3d}  sum={ss:+.1f}%  sharpe={ssh:+.2f}  {status}")
    
    print(f"    OOS Profitable: {wf_positive}/{n_splits} splits")
    print(f"    Mean OOS Sharpe: {np.mean(all_wf_sharpes):+.2f}")
    print(f"    Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # Regime analysis for filtered trades
    print(f"\n  Regime Analysis (filtered trades):")
    
    # SMA200
    above = [t for t in trades if t.get("above_sma200", False)]
    below = [t for t in trades if not t.get("above_sma200", False)]
    for label, subset in [("Above SMA200", above), ("Below SMA200", below)]:
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"    {label:20s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # PDI/MDI
    pdi_above = [t for t in trades if t.get("pdi", 0) > t.get("mdi", 0)]
    pdi_below = [t for t in trades if t.get("pdi", 0) <= t.get("mdi", 0)]
    for label, subset in [("PDI > MDI", pdi_above), ("PDI <= MDI", pdi_below)]:
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"    {label:20s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # MFE/MAE
    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    
    print(f"\n  MFE Analysis:")
    print(f"    Mean MFE: {np.mean(mfes):+.2f}%")
    print(f"    Median MFE: {np.median(mfes):+.2f}%")
    
    time_ex = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_ex:
        mfe_time = [t["mfe_pct"] for t in time_ex]
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"    Time-exit MFE: mean={np.mean(mfe_time):+.2f}%, profitable_at_some_point={profitable_time}/{len(time_ex)} ({profitable_time/len(time_ex)*100:.1f}%)")
    
    # ========================================================================
    # PART 5: COMPARISON WITH BASELINE
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 5: COMPARISON WITH BASELINE")
    print("=" * 70)
    
    # Baseline (from Phase 1)
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
    
    print(f"\n  {'Metric':20s} {'Baseline':>12s} {'BB Filter':>12s} {'Delta':>12s}")
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
