"""
Spring Reversal — Systematic BB %B Filter Expansion Sweep
=========================================================
The #1 limitation of Spring Reversal is trade count (78 trades over 7 years).
This script systematically sweeps BB %B lower/upper bounds to find the optimal
trade-off between signal count and Sharpe ratio.

Uses the optimized exits from prior research: s3.0%/t2.75%/h32.
Walk-forward validates top candidates.
Cross-validates on Binance.
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
        return {"trades": 0, "sum": 0.0, "compound": 0.0, "sharpe": 0.0,
                "sortino": 0.0, "max_dd": 0.0, "win_rate": 0.0,
                "avg_win": 0.0, "avg_loss": 0.0, "pf": 0.0, "max_consec": 0}
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
        "win_rate": len(wins) / len(pnls) * 100 if pnls else 0,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "pf": sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0,
        "max_consec": max_consec,
    }


def walk_forward_analysis(df, signal_series, params, n_splits=7):
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
    print("=" * 75)
    print("SPRING REVERSAL — SYSTEMATIC BB %B FILTER SWEEP")
    print("=" * 75)

    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")

    print(f"\nOKX: {len(df_okx)} bars, {df_okx.index[0]} → {df_okx.index[-1]}")
    print(f"Binance: {len(df_binance)} bars, {df_binance.index[0]} → {df_binance.index[-1]}")

    # =========================================================================
    # PREPARE DATA
    # =========================================================================
    df = df_okx.copy()
    df["sma200"] = sma(df["close"], 200)
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]

    # Core Spring signal (no filters)
    base_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    base_count = base_sig.sum()
    print(f"\nBase Spring signals (no filters): {base_count}")

    # SMA200-only filter
    sma200_only = base_sig & (df["close"] > df["sma200"])
    print(f"SMA200 filter only: {sma200_only.sum()}")

    # =========================================================================
    # GRID SWEEP: BB %B lower × upper bounds
    # =========================================================================
    print("\n" + "=" * 75)
    print("GRID SWEEP: BB %B Lower × Upper Bounds")
    print(f"Exits: stop=3.0%, target=2.75%, hold=32h, commission=5bps, slippage=5bps")
    print("=" * 75)

    base_exit_params = {
        "stop_pct": 3.0,
        "target_pct": 2.75,
        "max_hold": 32,
        "commission": 0.0005,
        "slippage": 0.0005,
    }

    # Sweep ranges
    # Lower bound: from very tight (0.25) to very loose (0.05)
    # Upper bound: from tight (0.45) to loose (0.80)
    bb_lows = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22]
    bb_highs = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]

    # Also include the current baseline and the vol-adaptive v1.1.0
    special_ranges = {
        "baseline [0.20, 0.60)": (0.20, 0.60),
        "v1.1.0  [0.15, 0.65)": (0.15, 0.65),
    }

    all_results = []

    # Sweep all combos
    for bb_low in bb_lows:
        for bb_high in bb_highs:
            if bb_low >= bb_high:
                continue  # invalid range
            # Apply filter: SMA200 + BB %B range
            sig = base_sig & (df["close"] > df["sma200"]) & \
                  (df["bb_pct_b"] >= bb_low) & (df["bb_pct_b"] < bb_high)
            n_sig = sig.sum()
            if n_sig < 20:  # too few trades to be meaningful
                continue
            trades = regime_backtest(df, sig, {}, **base_exit_params)
            m = compute_metrics(trades)
            all_results.append({
                "bb_low": bb_low,
                "bb_high": bb_high,
                "signals": n_sig,
                **m,
            })

    # Sort by Sharpe
    all_results.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n{'Rank':>4s} {'BB Range':>18s} {'Signals':>8s} {'Trades':>7s} "
          f"{'Sharpe':>7s} {'Return':>8s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 85)

    for i, r in enumerate(all_results[:30], 1):
        bb_range = f"[{r['bb_low']:.2f}, {r['bb_high']:.2f})"
        print(f"{i:>4d} {bb_range:>18s} {r['signals']:>8d} {r['trades']:>7d} "
              f"{r['sharpe']:>+7.2f} {r['sum']:>+7.1f}% {r['max_dd']:>+7.1f}% "
              f"{r['win_rate']:>5.1f}% {r['pf']:>5.2f}")

    # =========================================================================
    # IDENTIFY PARETO FRONTIER (trades vs Sharpe)
    # =========================================================================
    print("\n" + "=" * 75)
    print("PARETO-OPTIMAL CANDIDATES (non-dominated in Trades × Sharpe)")
    print("=" * 75)

    # Sort by trades ascending
    by_trades = sorted(all_results, key=lambda x: x["trades"])
    pareto = []
    max_sharpe_so_far = -999
    for r in by_trades:
        if r["sharpe"] > max_sharpe_so_far:
            max_sharpe_so_far = r["sharpe"]
            pareto.append(r)

    print(f"\n{'BB Range':>18s} {'Trades':>7s} {'Sharpe':>7s} {'Sum':>8s} "
          f"{'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'Signals':>8s}")
    print("-" * 80)
    for r in pareto:
        bb_range = f"[{r['bb_low']:.2f}, {r['bb_high']:.2f})"
        print(f"{bb_range:>18s} {r['trades']:>7d} {r['sharpe']:>+7.2f} "
              f"{r['sum']:>+7.1f}% {r['max_dd']:>+7.1f}% "
              f"{r['win_rate']:>5.1f}% {r['pf']:>5.2f} {r['signals']:>8d}")

    # =========================================================================
    # WALK-FORWARD: Top 6 candidates + baseline
    # =========================================================================
    print("\n" + "=" * 75)
    print("WALK-FORWARD VALIDATION (7 splits, OKX)")
    print("=" * 75)

    # Select candidates: Pareto frontier + baseline + v1.1.0
    candidates_to_wf = []

    # Add baseline and v1.1.0
    for r in all_results:
        if r["bb_low"] == 0.20 and r["bb_high"] == 0.60:
            candidates_to_wf.append(("baseline [0.20,0.60)", r))
        if r["bb_low"] == 0.15 and r["bb_high"] == 0.65:
            candidates_to_wf.append(("v1.1.0 [0.15,0.65)", r))

    # Add top Pareto candidates (up to 5 more)
    for r in pareto[:5]:
        label = f"[{r['bb_low']:.2f}, {r['bb_high']:.2f})"
        if not any(c[0] == label for c in candidates_to_wf):
            candidates_to_wf.append((label, r))

    # Also add top 3 by Sharpe not in Pareto
    for r in all_results[:3]:
        label = f"[{r['bb_low']:.2f}, {r['bb_high']:.2f})"
        if not any(c[0] == label for c in candidates_to_wf):
            candidates_to_wf.append((label, r))

    # De-duplicate
    seen = set()
    unique_candidates = []
    for label, r in candidates_to_wf:
        if label not in seen:
            seen.add(label)
            unique_candidates.append((label, r))
    candidates_to_wf = unique_candidates[:10]  # max 10

    wf_summary = []
    for label, info in candidates_to_wf:
        bb_low, bb_high = info["bb_low"], info["bb_high"]
        sig = base_sig & (df["close"] > df["sma200"]) & \
              (df["bb_pct_b"] >= bb_low) & (df["bb_pct_b"] < bb_high)

        wf = walk_forward_analysis(df, sig, base_exit_params, n_splits=7)
        wf_pos = sum(1 for r in wf if r["sum"] > 0)
        mean_sh = np.mean([r["sharpe"] for r in wf])
        total_sum = sum(r["sum"] for r in wf)

        print(f"\n--- {label} (full-period: {info['trades']} trades, Sharpe {info['sharpe']:+.2f}) ---")
        for r in wf:
            status = "✅" if r["sum"] > 0 else "❌"
            print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  "
                  f"trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
        print(f"  → {wf_pos}/7 profitable, mean OOS Sharpe: {mean_sh:+.2f}, total OOS: {total_sum:+.1f}%")

        wf_summary.append({
            "label": label,
            "full_trades": info["trades"],
            "full_sharpe": info["sharpe"],
            "full_sum": info["sum"],
            "full_maxdd": info["max_dd"],
            "wf_profitable": wf_pos,
            "mean_oos_sharpe": mean_sh,
            "total_oos_sum": total_sum,
            "split_details": wf,
        })

    # =========================================================================
    # WF SUMMARY TABLE
    # =========================================================================
    print("\n" + "=" * 75)
    print("WALK-FORWARD SUMMARY")
    print("=" * 75)
    wf_summary.sort(key=lambda x: x["mean_oos_sharpe"], reverse=True)

    print(f"\n{'Rank':>4s} {'BB Range':>18s} {'Full Tr':>7s} {'Full Sh':>7s} "
          f"{'Full DD':>7s} {'WF':>5s} {'Mean OOS Sh':>11s} {'OOS Sum':>8s}")
    print("-" * 85)
    for i, s in enumerate(wf_summary, 1):
        label = s["label"]
        if len(label) > 18:
            label = label[:17] + "…"
        print(f"{i:>4d} {label:>18s} {s['full_trades']:>7d} {s['full_sharpe']:>+7.2f} "
              f"{s['full_maxdd']:>+7.1f}% {s['wf_profitable']:>4d}/7 {s['mean_oos_sharpe']:>+11.2f} "
              f"{s['total_oos_sum']:>+7.1f}%")

    # =========================================================================
    # DETAILED BACKTEST: TOP CANDIDATE
    # =========================================================================
    top = wf_summary[0]
    print("\n" + "=" * 75)
    print(f"TOP CANDIDATE: {top['label']}")
    print("=" * 75)

    # Extract BB range
    label = top["label"]
    # Parse "[X.XX, Y.YY)"
    import re
    match = re.match(r'\[([\d.]+),\s*([\d.]+)\)', label)
    if match:
        bb_low = float(match.group(1))
        bb_high = float(match.group(2))
    else:
        # fallback: use baseline
        bb_low, bb_high = 0.20, 0.60

    best_sig = base_sig & (df["close"] > df["sma200"]) & \
               (df["bb_pct_b"] >= bb_low) & (df["bb_pct_b"] < bb_high)

    # Regime data for detailed analysis
    regime_data = {
        "above_sma200": (df["close"] > df["sma200"]).values,
        "bb_pct_b": df["bb_pct_b"].values,
    }

    trades = regime_backtest(df, best_sig, regime_data, **base_exit_params)
    m = compute_metrics(trades)

    print(f"\n  FULL BACKTEST RESULTS (OKX BTC/USDT 1h, 2019-2026)")
    print(f"  {'='*50}")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"  BB %%B Filter:       [{bb_low:.2f}, {bb_high:.2f})")
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
            print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(trades)*100:5.1f}%)  "
                  f"avg={np.mean(sp):+.2f}%  total={sum(sp):+.1f}%")

    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    print(f"\n  MFE: mean={np.mean(mfes):+.2f}%, median={np.median(mfes):+.2f}%, max={np.max(mfes):+.2f}%")
    print(f"  MAE: mean={np.mean(maes):+.2f}%, median={np.median(maes):+.2f}%, max={np.max(maes):+.2f}%")

    time_ex = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_ex:
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"\n  Time-exit profitable at some point: {profitable_time}/{len(time_ex)} "
              f"({profitable_time/len(time_ex)*100:.1f}%)")

    # =========================================================================
    # BASELINE COMPARISON (for reference)
    # =========================================================================
    print("\n" + "=" * 75)
    print("BASELINE COMPARISON (BB [0.20, 0.60) — original filter)")
    print("=" * 75)

    baseline_sig = base_sig & (df["close"] > df["sma200"]) & \
                   (df["bb_pct_b"] >= 0.20) & (df["bb_pct_b"] < 0.60)
    baseline_trades = regime_backtest(df, baseline_sig, {}, **base_exit_params)
    b_m = compute_metrics(baseline_trades)

    print(f"\n  {'Metric':25s} {'Baseline [0.20,0.60)':>20s} {'Top [{:.2f},{:.2f})'.format(bb_low, bb_high):>20s} {'Delta':>10s}")
    print(f"  {'-'*75}")
    comparisons = [
        ("Trades", b_m["trades"], m["trades"], lambda a, b: f"{b-a:+d}"),
        ("Compound Return", b_m["compound"], m["compound"], lambda a, b: f"{b-a:+.1f}%"),
        ("Linear Sum", b_m["sum"], m["sum"], lambda a, b: f"{b-a:+.1f}%"),
        ("Sharpe", b_m["sharpe"], m["sharpe"], lambda a, b: f"{b-a:+.2f}"),
        ("Sortino", b_m["sortino"], m["sortino"], lambda a, b: f"{b-a:+.2f}"),
        ("Max Drawdown", b_m["max_dd"], m["max_dd"], lambda a, b: f"{b-a:+.1f}%"),
        ("Win Rate", b_m["win_rate"], m["win_rate"], lambda a, b: f"{b-a:+.1f}%"),
        ("Avg Win", b_m["avg_win"], m["avg_win"], lambda a, b: f"{b-a:+.2f}%"),
        ("Avg Loss", b_m["avg_loss"], m["avg_loss"], lambda a, b: f"{b-a:+.2f}%"),
        ("Profit Factor", b_m["pf"], m["pf"], lambda a, b: f"{b-a:+.2f}"),
        ("Max Consec", b_m["max_consec"], m["max_consec"], lambda a, b: f"{b-a:+d}"),
    ]
    for name, a, b, fmt in comparisons:
        if "Return" in name or "Drawdown" in name or "Rate" in name:
            a_str = f"{a:+.1f}%"
            b_str = f"{b:+.1f}%"
        elif name == "Trades" or name == "Max Consec":
            a_str = f"{a}"
            b_str = f"{b}"
        else:
            a_str = f"{a:+.2f}"
            b_str = f"{b:+.2f}"
        delta = fmt(a, b)
        print(f"  {name:25s} {a_str:>20s} {b_str:>20s} {delta:>10s}")

    # =========================================================================
    # BINANCE CROSS-VALIDATION
    # =========================================================================
    print("\n" + "=" * 75)
    print("BINANCE CROSS-VALIDATION")
    print("=" * 75)

    df_b = df_binance.copy()
    df_b["sma200"] = sma(df_b["close"], 200)
    bb_b = bollinger_bands(df_b, 20, 2.0)
    df_b["bb_pct_b"] = bb_b["pct_b"]

    sig_b = spring_signal(df_b, lookback=20, vol_mult=1.5, close_pct=0.5)

    # Top candidate on Binance
    best_sig_b = sig_b & (df_b["close"] > df_b["sma200"]) & \
                 (df_b["bb_pct_b"] >= bb_low) & (df_b["bb_pct_b"] < bb_high)
    
    trades_b = regime_backtest(df_b, best_sig_b, {}, **base_exit_params)
    if trades_b:
        m_b = compute_metrics(trades_b)
        print(f"\n  Total Trades:       {m_b['trades']}")
        print(f"  Linear Sum:         {m_b['sum']:+.1f}%")
        print(f"  Sharpe Ratio:       {m_b['sharpe']:+.2f}")
        print(f"  Win Rate:           {m_b['win_rate']:.1f}%")
        print(f"  Profit Factor:      {m_b['pf']:.2f}")
        print(f"  Max Drawdown:       {m_b['max_dd']:+.1f}%")

        print(f"\n  Cross-Exchange:")
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
        print(f"\n  Binance Walk-Forward (7 splits):")
        wf_b = walk_forward_analysis(df_b, best_sig_b, base_exit_params, n_splits=7)
        wf_pos_b = 0
        all_sh_b = []
        for r in wf_b:
            status = "✅" if r["sum"] > 0 else "❌"
            if r["sum"] > 0:
                wf_pos_b += 1
            all_sh_b.append(r["sharpe"])
            print(f"    Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  "
                  f"trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
        print(f"    → {wf_pos_b}/7 profitable, mean OOS Sharpe: {np.mean(all_sh_b):+.2f}")

    # =========================================================================
    # TRADE-OFF ANALYSIS: Signal count vs per-signal quality
    # =========================================================================
    print("\n" + "=" * 75)
    print("TRADE-OFF: BB %B Lower Bound vs Signal Quality")
    print("=" * 75)

    # For a fixed upper bound of 0.65 (the v1.1.0 upper), sweep lower bounds
    print(f"\n  Fixing upper bound = 0.65, varying lower bound:")
    print(f"  {'BB Low':>8s} {'Signals':>8s} {'Trades':>7s} {'Sharpe':>7s} "
          f"{'Sum':>8s} {'MaxDD':>7s} {'WF':>5s}")
    print(f"  {'-'*65}")

    for bb_low in [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25]:
        sig = base_sig & (df["close"] > df["sma200"]) & \
              (df["bb_pct_b"] >= bb_low) & (df["bb_pct_b"] < 0.65)
        n_sig = sig.sum()
        if n_sig < 20:
            continue
        t = regime_backtest(df, sig, {}, **base_exit_params)
        if t:
            m2 = compute_metrics(t)
            # Quick WF
            wf2 = walk_forward_analysis(df, sig, base_exit_params, n_splits=7)
            wf_pos2 = sum(1 for r in wf2 if r["sum"] > 0)
            print(f"  {bb_low:>8.2f} {n_sig:>8d} {m2['trades']:>7d} {m2['sharpe']:>+7.2f} "
                  f"{m2['sum']:>+7.1f}% {m2['max_dd']:>+7.1f}% {wf_pos2:>4d}/7")

    print("\n" + "=" * 75)
    print("DONE")
    print("=" * 75)


if __name__ == "__main__":
    main()
