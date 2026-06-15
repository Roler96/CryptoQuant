"""
Spring Reversal — Phase 2: Regime-Filtered Optimization
========================================================

Phase 1 findings:
- Baseline Sharpe -0.71, Max DD -55% — signal is negative unfiltered
- BUT: Above SMA200 + PDI>MDI → 27 trades, Sharpe +1.79
- Above SMA200 + RSI>=50 → 43 trades, Sharpe +1.18
- BB %B 0.2-0.6 → 192 trades, sum +99.6%
- Drop regime (-5 to -2% 48h) → 137 trades, Sharpe +1.25
- 98.2% of time-exits had positive MFE — exits are too slow

Phase 2 agenda:
1. Test the "lower the target" pattern (time-exits mostly unprofitable despite MFE)
2. Test regime filter combos with exit optimization
3. Walk-forward validate the best combo
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

# Import signal function from phase 1
from backtest_spring_reversal import spring_signal, regime_backtest, walk_forward


def apply_regime_filters(df, signals, filters):
    """Apply regime filters to signals and return filtered Series."""
    result = signals.copy()
    for name, cond in filters:
        result = result & cond
    return result


def main():
    print("=" * 70)
    print("SPRING REVERSAL — PHASE 2: REGIME-FILTERED OPTIMIZATION")
    print("=" * 70)
    
    # Load data
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nOKX data: {len(df)} bars, {df.index[0]} to {df.index[-1]}")
    
    # Compute all regime indicators
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
    
    # ========================================================================
    # DEFINE FILTERS
    # ========================================================================
    
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
    
    # ========================================================================
    # PART 1: TARGET OPTIMIZATION WITH REGIME FILTERS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 1: LOWER THE TARGET PATTERN")
    print("=" * 70)
    
    print("\nTime-exit MFE analysis from Phase 1:")
    print("  98.2% of time-exits were profitable at some point")
    print("  Mean MFE: +1.93% but final exit: +0.47%")
    print("  → Target is too high — letting +2% drift back to 0%")
    
    # Test lower targets with fixed stop and hold
    stop = 3.0
    hold = 16
    
    print(f"\n--- Target Sweep (stop={stop}%, hold={hold}h) ---")
    print(f"{'Target':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print(f"{'':>8} {'':>7} {'':>8} {'':>7} {'':>6} {'':>6} {'StopRate':>9}")
    print("-" * 62)
    
    for tp in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 4.0, 5.0]:
        params = {"stop_pct": stop, "target_pct": tp, "max_hold": hold,
                  "commission": 0.0005, "slippage": 0.0005}
        t = regime_backtest(df, base_sig, {}, **params)
        if t:
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
            stop_rate = sum(1 for x in t if x["exit_reason"] == "stop_loss") / len(t) * 100
            tp_rate = sum(1 for x in t if x["exit_reason"] == "take_profit") / len(t) * 100
            print(f"{tp:>7.1f}% {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # ========================================================================
    # PART 2: REGIME-FILTERED TARGET SWEEP
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 2: REGIME-FILTERED OPTIMIZATION")
    print("=" * 70)
    
    # Define filter combinations to test
    filter_combos = [
        ("No filter (baseline)", []),
        ("SMA200 only", [("sma200", df["close"] > df["sma200"])]),
        ("SMA200 + PDI>MDI", [
            ("sma200", df["close"] > df["sma200"]),
            ("pdi_above", df["pdi"] > df["mdi"]),
        ]),
        ("SMA200 + RSI>=50", [
            ("sma200", df["close"] > df["sma200"]),
            ("rsi_above_50", df["rsi14"] >= 50),
        ]),
        ("SMA200 + PDI>MDI + RSI>=50", [
            ("sma200", df["close"] > df["sma200"]),
            ("pdi_above", df["pdi"] > df["mdi"]),
            ("rsi_above_50", df["rsi14"] >= 50),
        ]),
        ("SMA200 + BB 0.2-0.6", [
            ("sma200", df["close"] > df["sma200"]),
            ("bb_mid", (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)),
        ]),
        ("SMA200 + DD48 -5to-2%", [
            ("sma200", df["close"] > df["sma200"]),
            ("dd48_drop", (df["dd48"] >= -5) & (df["dd48"] < -2)),
        ]),
        ("SMA200 + PDI>MDI + DD48 -5to-2%", [
            ("sma200", df["close"] > df["sma200"]),
            ("pdi_above", df["pdi"] > df["mdi"]),
            ("dd48_drop", (df["dd48"] >= -5) & (df["dd48"] < -2)),
        ]),
    ]
    
    # Test each filter combo with optimized exits
    for filter_name, filters in filter_combos:
        filtered_sig = apply_regime_filters(df, base_sig, filters)
        sig_count = filtered_sig.sum()
        
        # Test with different exit params
        best_result = None
        best_target = None
        
        for tp in [1.2, 1.5, 1.8, 2.0, 2.5, 3.0]:
            params = {"stop_pct": stop, "target_pct": tp, "max_hold": hold,
                      "commission": 0.0005, "slippage": 0.0005}
            t = regime_backtest(df, filtered_sig, {}, **params)
            if t:
                p = [x["pnl_pct"] for x in t]
                s = sum(p)
                sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
                
                eq = [10000]
                for x in p:
                    eq.append(eq[-1] * (1 + x / 100))
                eq = np.array(eq)
                dd_val = (eq - np.maximum.accumulate(eq)).min() / np.maximum.accumulate(eq).max() * 100
                
                if best_result is None or sh > best_result[0]:
                    best_result = (sh, s, dd_val, len(t), tp, p)
                    best_target = tp
        
        if best_result:
            sh, s, dd_val, ntrades, tp, p = best_result
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            w = [x for x in p if x > 0]
            l = [x for x in p if x <= 0]
            pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
            # Avg max favorable excursion for time exits
            tt = regime_backtest(df, filtered_sig, {}, stop_pct=stop, target_pct=tp, 
                                 max_hold=hold, commission=0.0005, slippage=0.0005)
            time_ex = [t for t in tt if t["exit_reason"] == "time_exit"]
            mfe_time = np.mean([t["mfe_pct"] for t in time_ex]) if time_ex else 0
            
            print(f"\n  {filter_name} (sig_count={sig_count}, best_target={tp:.1f}%):")
            print(f"    Trades={ntrades:4d}  Sum={s:+.1f}%  Sharpe={sh:+.2f}  WR={wr:.1f}%  PF={pf_val:.2f}  MaxDD={dd_val:+.1f}%")
            print(f"    Avg time-exit MFE={mfe_time:+.2f}%")
    
    # ========================================================================
    # PART 3: BEST COMBO — DEEP EXIT OPTIMIZATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 3: DEEP EXIT OPT FOR BEST REGIME COMBO")
    print("=" * 70)
    
    # Based on Part 2 results, pick the best filter combo and optimize exits more deeply
    # We'll test: SMA200 + PDI>MDI (most concentrated edge)
    # and SMA200 + RSI>=50 (more trades)
    
    best_filters_configs = [
        ("SMA200 + PDI>MDI", [
            ("sma200", df["close"] > df["sma200"]),
            ("pdi_above", df["pdi"] > df["mdi"]),
        ]),
        ("SMA200 + RSI>=50", [
            ("sma200", df["close"] > df["sma200"]),
            ("rsi_above_50", df["rsi14"] >= 50),
        ]),
        ("SMA200 + PDI>MDI + RSI>=50", [
            ("sma200", df["close"] > df["sma200"]),
            ("pdi_above", df["pdi"] > df["mdi"]),
            ("rsi_above_50", df["rsi14"] >= 50),
        ]),
    ]
    
    for fb_name, fb_filters in best_filters_configs:
        fb_sig = apply_regime_filters(df, base_sig, fb_filters)
        print(f"\n{'='*50}")
        print(f"DEEP OPT: {fb_name}")
        print(f"Signal count: {fb_sig.sum()}")
        print(f"{'='*50}")
        
        # Full grid search
        print(f"\n  {'Stop':>6} {'Target':>7} {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7} {'TP%':>6} {'SL%':>6}")
        print(f"  {'-'*76}")
        
        best_overall = None
        
        for sl in [2.0, 2.5, 3.0, 3.5, 4.0]:
            for tp in [1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 4.0]:
                for hh in [12, 16, 20, 24, 32]:
                    params = {"stop_pct": sl, "target_pct": tp, "max_hold": hh,
                              "commission": 0.0005, "slippage": 0.0005}
                    t = regime_backtest(df, fb_sig, {}, **params)
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
                        tp_rate = sum(1 for x in t if x["exit_reason"] == "take_profit") / len(t) * 100
                        sl_rate = sum(1 for x in t if x["exit_reason"] == "stop_loss") / len(t) * 100
                        
                        if best_overall is None or sh > best_overall[0]:
                            best_overall = (sh, s, dd_val, wr, pf_val, sl, tp, hh, len(t), tp_rate, sl_rate, t)
    
    # ========================================================================
    # PART 4: WALK-FORWARD ON BEST COMBO
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 4: WALK-FORWARD — BEST REGIME FILTER COMBO")
    print("=" * 70)
    
    for fb_name, fb_filters in best_filters_configs:
        print(f"\n{'='*50}")
        print(f"WALK-FORWARD: {fb_name}")
        print(f"{'='*50}")
        
        # Find best params for this filter combo
        fb_sig = apply_regime_filters(df, base_sig, fb_filters)
        
        best_local = None
        for sl in [2.5, 3.0, 3.5, 4.0]:
            for tp in [1.5, 2.0, 2.5, 3.0]:
                for hh in [16, 20, 24]:
                    params = {"stop_pct": sl, "target_pct": tp, "max_hold": hh,
                              "commission": 0.0005, "slippage": 0.0005}
                    t = regime_backtest(df, fb_sig, {}, **params)
                    if t and len(t) >= 10:
                        p = [x["pnl_pct"] for x in t]
                        sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
                        if best_local is None or sh > best_local[0]:
                            best_local = (sh, sl, tp, hh, t)
        
        if best_local:
            best_sh, best_sl, best_tp, best_hh, best_t = best_local
            bp = [x["pnl_pct"] for x in best_t]
            bs = sum(bp)
            bwr = sum(1 for x in bp if x > 0) / len(bp) * 100
            beq = [10000]
            for x in bp:
                beq.append(beq[-1] * (1 + x / 100))
            beq = np.array(beq)
            bdd = (beq - np.maximum.accumulate(beq)).min() / np.maximum.accumulate(beq).max() * 100
            bw = [x for x in bp if x > 0]
            bl = [x for x in bp if x <= 0]
            bpf = sum(bw) / abs(sum(bl)) if bl and sum(bl) != 0 else 0
            
            print(f"\n  Best params: stop={best_sl}%, target={best_tp}%, hold={best_hh}h")
            print(f"  Full period: trades={len(best_t)}, sum={bs:+.1f}%, sharpe={best_sh:+.2f}, wr={bwr:.1f}%, pf={bpf:.2f}, maxdd={bdd:+.1f}%")
            
            # Walk-forward
            def make_wf_signal_func(filters_df, filters_list, sl, tp, hh):
                def wf_signal_func(d):
                    # Compute regime indicators on split data
                    d = d.copy()
                    d["sma200"] = sma(d["close"], 200)
                    base_s = spring_signal(d, lookback=20, vol_mult=1.5, close_pct=0.5)
                    
                    filtered = base_s.copy()
                    for name, cond_template in filters_list:
                        if name == "sma200":
                            filtered = filtered & (d["close"] > d["sma200"])
                        elif name == "pdi_above":
                            a = adx_func(d, 14)
                            filtered = filtered & (a["pdi"] > a["mdi"])
                        elif name == "rsi_above_50":
                            filtered = filtered & (rsi(d["close"], 14) >= 50)
                    return filtered
                return wf_signal_func
            
            # Need to recompute indicators per split for walk-forward
            # Use a simpler approach: compute on full df and apply to each split
            full_filtered_sig = apply_regime_filters(df, base_sig, fb_filters)
            
            # Walk forward using pre-computed signals
            wf_params = {"stop_pct": best_sl, "target_pct": best_tp, "max_hold": best_hh,
                         "commission": 0.0005, "slippage": 0.0005}
            
            n = len(df)
            slot = len(df) // 8
            n_splits = 6
            
            for s in range(n_splits):
                start = n - (n_splits - s + 1) * slot
                end = min(n, start + slot)
                split_sig = full_filtered_sig.iloc[start:end]
                split_df = df.iloc[start:end]
                t = regime_backtest(split_df, split_sig, {}, **wf_params)
                
                if t:
                    p = [x["pnl_pct"] for x in t]
                    ss = sum(p)
                    ssh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
                else:
                    ss = 0
                    ssh = 0
                
                status = "✅" if ss > 0 else "❌"
                print(f"  Split {s+1}: {split_df.index[0].strftime('%Y-%m')}→{split_df.index[-1].strftime('%Y-%m')}  trades={len(t):3d}  sum={ss:+.1f}%  sharpe={ssh:+.2f}  {status}")
    
    # ========================================================================
    # PART 5: BB %B FILTER EXPLORATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 5: BOLLINGER %B FILTER EXPLORATION")
    print("=" * 70)
    
    # Phase 1 showed BB %B 0.2-0.6 was very strong: 192 trades, +99.6%
    # Let's test this as a simpler, higher-trade-count filter
    
    bb_filter = ("BB 0.2-0.6", [
        ("bb_mid", (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)),
    ])
    
    for fb_name, fb_filters in [bb_filter]:
        fb_sig = apply_regime_filters(df, base_sig, fb_filters)
        print(f"\n  {fb_name}: signal_count={fb_sig.sum()}")
        
        print(f"\n  {'Stop':>6} {'Target':>7} {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7} {'TP%':>6} {'SL%':>6}")
        print(f"  {'-'*76}")
        
        for sl in [2.5, 3.0, 3.5, 4.0]:
            for tp in [1.5, 2.0, 2.5, 3.0, 4.0]:
                for hh in [16, 20, 24, 32]:
                    params = {"stop_pct": sl, "target_pct": tp, "max_hold": hh,
                              "commission": 0.0005, "slippage": 0.0005}
                    t = regime_backtest(df, fb_sig, {}, **params)
                    if t and len(t) >= 15:
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
                        tp_rate = sum(1 for x in t if x["exit_reason"] == "take_profit") / len(t) * 100
                        sl_rate = sum(1 for x in t if x["exit_reason"] == "stop_loss") / len(t) * 100
                        
                        if sh > 0.3:
                            print(f"  {sl:>5.1f}% {tp:>6.1f}% {hh:>5}h {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}% {tp_rate:>5.1f}% {sl_rate:>5.1f}%")
        
        # Walk-forward on BB filter
        print(f"\n  Walk-Forward for BB 0.2-0.6 (stop=3.5%, target=3.0%, hold=24h):")
        best_params = {"stop_pct": 3.5, "target_pct": 3.0, "max_hold": 24,
                       "commission": 0.0005, "slippage": 0.0005}
        
        n = len(df)
        slot = len(df) // 8
        n_splits = 6
        
        wf_positive = 0
        total_wf_sum = 0
        all_wf_sharpes = []
        
        for s in range(n_splits):
            start = n - (n_splits - s + 1) * slot
            end = min(n, start + slot)
            split_sig = fb_sig.iloc[start:end]
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
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
