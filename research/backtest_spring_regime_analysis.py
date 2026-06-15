"""
Spring Reversal — Comprehensive Regime Analysis
================================================

Tag every trade with market conditions at entry time.
Identify toxic regimes and profitable regimes.
Test combined filters with walk-forward validation.

Uses the same regime_backtest() and spring_signal() from backtest_spring_reversal.py.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import (
    sma, ema, atr as atr_func, adx as adx_func,
    pct_change_rolling, rsi, bollinger_bands
)

# Import from existing research script
from backtest_spring_reversal import spring_signal, regime_backtest


def print_regime_table(title, regimes, trades):
    """Print a formatted regime analysis table."""
    print(f"\n--- {title} ---")
    print(f"{'Regime':30s} {'Trades':>6s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'Stop%':>6s}")
    print("-" * 75)
    for label, condition_fn in regimes:
        subset = [t for t in trades if condition_fn(t)]
        if not subset:
            continue
        p = [t["pnl_pct"] for t in subset]
        s = sum(p)
        sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
        wr = sum(1 for x in p if x > 0) / len(p) * 100
        w = [x for x in p if x > 0]
        l = [x for x in p if x <= 0]
        pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else float('inf')
        stop_rate = sum(1 for t in subset if t["exit_reason"] == "stop_loss") / len(subset) * 100
        print(f"{label:30s} {len(subset):>6d} {s:>+7.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {stop_rate:>5.1f}%")


def print_combined_regimes(title, regimes, trades):
    """Print combined regime analysis."""
    print(f"\n--- {title} ---")
    print(f"{'Regime':45s} {'Trades':>6s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'Stop%':>6s}")
    print("-" * 90)
    for label, condition_fn in regimes:
        subset = [t for t in trades if condition_fn(t)]
        if not subset:
            continue
        p = [t["pnl_pct"] for t in subset]
        s = sum(p)
        sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
        wr = sum(1 for x in p if x > 0) / len(p) * 100
        w = [x for x in p if x > 0]
        l = [x for x in p if x <= 0]
        pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else float('inf')
        stop_rate = sum(1 for t in subset if t["exit_reason"] == "stop_loss") / len(subset) * 100
        print(f"{label:45s} {len(subset):>6d} {s:>+7.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {stop_rate:>5.1f}%")


def walk_forward_analysis(df, signal_series, params, n_splits=6):
    """Run walk-forward validation."""
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


def compute_metrics(trades):
    """Compute standard metrics from trade list."""
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


def main():
    print("=" * 70)
    print("SPRING REVERSAL — COMPREHENSIVE REGIME ANALYSIS")
    print("=" * 70)
    
    # Load data
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    print(f"\nOKX: {len(df_okx)} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance: {len(df_binance)} bars, {df_binance.index[0]} to {df_binance.index[-1]}")
    
    # ========================================================================
    # Compute all indicators
    # ========================================================================
    df = df_okx.copy()
    df["sma200"] = sma(df["close"], 200)
    df["sma50"] = sma(df["close"], 50)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    
    adx_df = adx_func(df, 14)
    df["adx"] = adx_df["adx"]
    df["pdi"] = adx_df["pdi"]
    df["mdi"] = adx_df["mdi"]
    
    df["atr14"] = atr_func(df, 14)
    df["median_atr200"] = df["atr14"].rolling(200).median()
    df["vol_ratio"] = df["atr14"] / df["median_atr200"]
    
    df["rsi14"] = rsi(df["close"], 14)
    df["dd48"] = pct_change_rolling(df["close"], 48)
    df["dd168"] = pct_change_rolling(df["close"], 168)
    df["dd24"] = pct_change_rolling(df["close"], 24)
    
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]
    
    # Day of week, hour of day
    df["day_of_week"] = df.index.dayofweek
    df["hour"] = df.index.hour
    
    # 200-day return (macro trend)
    df["ret200d"] = pct_change_rolling(df["close"], 200 * 24)
    
    # ========================================================================
    # Generate baseline signal
    # ========================================================================
    signals = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    signal_count = signals.sum()
    print(f"\nSignal count: {signal_count}")
    
    # Regime data dict
    regime_data = {
        "above_sma200": (df["close"] > df["sma200"]).values,
        "above_sma50": (df["close"] > df["sma50"]).values,
        "above_ema200": (df["close"] > df["ema200"]).values,
        "ema50_above_ema200": (df["ema50"] > df["ema200"]).values,
        "adx": df["adx"].values,
        "pdi": df["pdi"].values,
        "mdi": df["mdi"].values,
        "vol_ratio": df["vol_ratio"].values,
        "rsi14": df["rsi14"].values,
        "dd48": df["dd48"].values,
        "dd168": df["dd168"].values,
        "dd24": df["dd24"].values,
        "bb_pct_b": df["bb_pct_b"].values,
        "day_of_week": df["day_of_week"].values,
        "hour": df["hour"].values,
        "ret200d": df["ret200d"].values,
    }
    
    # ========================================================================
    # PART 1: BASELINE BACKTEST (unfiltered)
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 1: BASELINE BACKTEST (UNFILTERED)")
    print("=" * 70)
    
    baseline_params = {
        "stop_pct": 3.0,
        "target_pct": 5.0,
        "max_hold": 24,
        "commission": 0.0005,
        "slippage": 0.0005,
    }
    
    trades = regime_backtest(df, signals, regime_data, **baseline_params)
    
    if not trades:
        print("ERROR: No trades generated!")
        return
    
    m = compute_metrics(trades)
    
    print(f"\n  Total Trades:       {m['trades']}")
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
    
    # ========================================================================
    # PART 2: SINGLE-DIMENSION REGIME ANALYSIS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 2: SINGLE-DIMENSION REGIME ANALYSIS")
    print("=" * 70)
    
    # 1. SMA200
    print_regime_table("SMA200 Regime", [
        ("Above SMA200", lambda t: t.get("above_sma200", False)),
        ("Below SMA200", lambda t: not t.get("above_sma200", False)),
    ], trades)
    
    # 2. SMA50
    print_regime_table("SMA50 Regime", [
        ("Above SMA50", lambda t: t.get("above_sma50", False)),
        ("Below SMA50", lambda t: not t.get("above_sma50", False)),
    ], trades)
    
    # 3. PDI vs MDI
    print_regime_table("Directional Movement (PDI vs MDI)", [
        ("PDI > MDI (bullish)", lambda t: t.get("pdi", 0) > t.get("mdi", 0)),
        ("PDI <= MDI (bearish)", lambda t: t.get("pdi", 0) <= t.get("mdi", 0)),
    ], trades)
    
    # 4. ADX (trend strength)
    print_regime_table("ADX Trend Strength", [
        ("ADX > 30 (very strong)", lambda t: t.get("adx", 0) > 30),
        ("ADX 25-30 (strong)", lambda t: 25 < t.get("adx", 0) <= 30),
        ("ADX 20-25 (moderate)", lambda t: 20 < t.get("adx", 0) <= 25),
        ("ADX <= 20 (weak/ranging)", lambda t: t.get("adx", 0) <= 20),
    ], trades)
    
    # 5. RSI
    print_regime_table("RSI(14) Regime", [
        ("RSI < 30 (oversold)", lambda t: t.get("rsi14", 50) < 30),
        ("RSI 30-40", lambda t: 30 <= t.get("rsi14", 50) < 40),
        ("RSI 40-50", lambda t: 40 <= t.get("rsi14", 50) < 50),
        ("RSI 50-60", lambda t: 50 <= t.get("rsi14", 50) < 60),
        ("RSI 60-70", lambda t: 60 <= t.get("rsi14", 50) < 70),
        ("RSI >= 70 (overbought)", lambda t: t.get("rsi14", 50) >= 70),
    ], trades)
    
    # 6. Bollinger %B
    print_regime_table("Bollinger %B Regime", [
        ("%B < 0 (below lower)", lambda t: t.get("bb_pct_b", 0.5) < 0),
        ("%B 0-0.2", lambda t: 0 <= t.get("bb_pct_b", 0.5) < 0.2),
        ("%B 0.2-0.4", lambda t: 0.2 <= t.get("bb_pct_b", 0.5) < 0.4),
        ("%B 0.4-0.6", lambda t: 0.4 <= t.get("bb_pct_b", 0.5) < 0.6),
        ("%B 0.6-0.8", lambda t: 0.6 <= t.get("bb_pct_b", 0.5) < 0.8),
        ("%B 0.8-1.0", lambda t: 0.8 <= t.get("bb_pct_b", 0.5) < 1.0),
        ("%B >= 1.0 (above upper)", lambda t: t.get("bb_pct_b", 0.5) >= 1.0),
    ], trades)
    
    # 7. 48h Price Change
    print_regime_table("48h Price Change", [
        ("Crash (<-5%)", lambda t: t.get("dd48", 0) < -5),
        ("Drop (-5 to -2%)", lambda t: -5 <= t.get("dd48", 0) < -2),
        ("Flat (-2 to 0%)", lambda t: -2 <= t.get("dd48", 0) < 0),
        ("Mild up (0 to 2%)", lambda t: 0 <= t.get("dd48", 0) < 2),
        ("Rally (2 to 5%)", lambda t: 2 <= t.get("dd48", 0) < 5),
        ("Strong rally (>5%)", lambda t: t.get("dd48", 0) >= 5),
    ], trades)
    
    # 8. 24h Price Change
    print_regime_table("24h Price Change", [
        ("Crash (<-3%)", lambda t: t.get("dd24", 0) < -3),
        ("Drop (-3 to -1%)", lambda t: -3 <= t.get("dd24", 0) < -1),
        ("Flat (-1 to 1%)", lambda t: -1 <= t.get("dd24", 0) < 1),
        ("Rally (1 to 3%)", lambda t: 1 <= t.get("dd24", 0) < 3),
        ("Strong rally (>3%)", lambda t: t.get("dd24", 0) >= 3),
    ], trades)
    
    # 9. Volatility (ATR ratio)
    print_regime_table("Volatility Regime (ATR ratio)", [
        ("Very Low (<0.6)", lambda t: t.get("vol_ratio", 1.0) < 0.6),
        ("Low (0.6-0.8)", lambda t: 0.6 <= t.get("vol_ratio", 1.0) < 0.8),
        ("Normal (0.8-1.2)", lambda t: 0.8 <= t.get("vol_ratio", 1.0) < 1.2),
        ("High (1.2-1.5)", lambda t: 1.2 <= t.get("vol_ratio", 1.0) < 1.5),
        ("Very High (>1.5)", lambda t: t.get("vol_ratio", 1.0) >= 1.5),
    ], trades)
    
    # 10. Day of Week
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    print_regime_table("Day of Week", [
        (day_names[d], lambda t, d=d: t.get("day_of_week", 0) == d)
        for d in range(7)
    ], trades)
    
    # 11. Hour of Day (UTC)
    print_regime_table("Hour of Day (UTC)", [
        (f"{h:02d}:00 UTC", lambda t, h=h: t.get("hour", 0) == h)
        for h in range(24)
    ], trades)
    
    # 12. 200-day Return (macro trend)
    print_regime_table("200-Day Return (Macro Trend)", [
        ("Bear (<-20%)", lambda t: t.get("ret200d", 0) < -20),
        ("Weak bear (-20 to 0%)", lambda t: -20 <= t.get("ret200d", 0) < 0),
        ("Weak bull (0 to 50%)", lambda t: 0 <= t.get("ret200d", 0) < 50),
        ("Bull (50 to 200%)", lambda t: 50 <= t.get("ret200d", 0) < 200),
        ("Strong bull (>200%)", lambda t: t.get("ret200d", 0) >= 200),
    ], trades)
    
    # 13. EMA50 vs EMA200
    print_regime_table("EMA50 vs EMA200 (Golden Cross)", [
        ("EMA50 > EMA200 (bullish)", lambda t: t.get("ema50_above_ema200", False)),
        ("EMA50 <= EMA200 (bearish)", lambda t: not t.get("ema50_above_ema200", False)),
    ], trades)
    
    # ========================================================================
    # PART 3: COMBINED REGIME ANALYSIS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 3: COMBINED REGIME ANALYSIS")
    print("=" * 70)
    
    # SMA200 × PDI/MDI
    print_combined_regimes("SMA200 × PDI/MDI", [
        ("Above SMA200 + PDI > MDI", lambda t: t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0)),
        ("Above SMA200 + PDI <= MDI", lambda t: t.get("above_sma200", False) and t.get("pdi", 0) <= t.get("mdi", 0)),
        ("Below SMA200 + PDI > MDI", lambda t: not t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0)),
        ("Below SMA200 + PDI <= MDI", lambda t: not t.get("above_sma200", False) and t.get("pdi", 0) <= t.get("mdi", 0)),
    ], trades)
    
    # SMA200 × ADX
    print_combined_regimes("SMA200 × ADX", [
        ("Above SMA200 + ADX > 25", lambda t: t.get("above_sma200", False) and t.get("adx", 0) > 25),
        ("Above SMA200 + ADX <= 25", lambda t: t.get("above_sma200", False) and t.get("adx", 0) <= 25),
        ("Below SMA200 + ADX > 25", lambda t: not t.get("above_sma200", False) and t.get("adx", 0) > 25),
        ("Below SMA200 + ADX <= 25", lambda t: not t.get("above_sma200", False) and t.get("adx", 0) <= 25),
    ], trades)
    
    # SMA200 × 48h
    print_combined_regimes("SMA200 × 48h Price Change", [
        ("Above SMA200 + 48h > 0%", lambda t: t.get("above_sma200", False) and t.get("dd48", 0) > 0),
        ("Above SMA200 + 48h <= 0%", lambda t: t.get("above_sma200", False) and t.get("dd48", 0) <= 0),
        ("Below SMA200 + 48h > 0%", lambda t: not t.get("above_sma200", False) and t.get("dd48", 0) > 0),
        ("Below SMA200 + 48h <= 0%", lambda t: not t.get("above_sma200", False) and t.get("dd48", 0) <= 0),
    ], trades)
    
    # SMA200 × RSI
    print_combined_regimes("SMA200 × RSI", [
        ("Above SMA200 + RSI < 40", lambda t: t.get("above_sma200", False) and t.get("rsi14", 50) < 40),
        ("Above SMA200 + RSI 40-60", lambda t: t.get("above_sma200", False) and 40 <= t.get("rsi14", 50) < 60),
        ("Above SMA200 + RSI >= 60", lambda t: t.get("above_sma200", False) and t.get("rsi14", 50) >= 60),
        ("Below SMA200 + RSI < 40", lambda t: not t.get("above_sma200", False) and t.get("rsi14", 50) < 40),
        ("Below SMA200 + RSI 40-60", lambda t: not t.get("above_sma200", False) and 40 <= t.get("rsi14", 50) < 60),
        ("Below SMA200 + RSI >= 60", lambda t: not t.get("above_sma200", False) and t.get("rsi14", 50) >= 60),
    ], trades)
    
    # BB %B × SMA200
    print_combined_regimes("BB %B × SMA200", [
        ("Above SMA200 + %B < 0.2", lambda t: t.get("above_sma200", False) and t.get("bb_pct_b", 0.5) < 0.2),
        ("Above SMA200 + %B 0.2-0.6", lambda t: t.get("above_sma200", False) and 0.2 <= t.get("bb_pct_b", 0.5) < 0.6),
        ("Above SMA200 + %B >= 0.6", lambda t: t.get("above_sma200", False) and t.get("bb_pct_b", 0.5) >= 0.6),
        ("Below SMA200 + %B < 0.2", lambda t: not t.get("above_sma200", False) and t.get("bb_pct_b", 0.5) < 0.2),
        ("Below SMA200 + %B 0.2-0.6", lambda t: not t.get("above_sma200", False) and 0.2 <= t.get("bb_pct_b", 0.5) < 0.6),
        ("Below SMA200 + %B >= 0.6", lambda t: not t.get("above_sma200", False) and t.get("bb_pct_b", 0.5) >= 0.6),
    ], trades)
    
    # ========================================================================
    # PART 4: FILTER TESTING
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 4: FILTER TESTING (Post-Hoc)")
    print("=" * 70)
    
    filters = [
        ("Baseline (no filter)", lambda t: True),
        ("SMA200 only", lambda t: t.get("above_sma200", False)),
        ("PDI > MDI only", lambda t: t.get("pdi", 0) > t.get("mdi", 0)),
        ("ADX > 25 only", lambda t: t.get("adx", 0) > 25),
        ("48h > -2% only", lambda t: t.get("dd48", 0) > -2),
        ("48h > 0% only", lambda t: t.get("dd48", 0) > 0),
        ("RSI < 70 only", lambda t: t.get("rsi14", 50) < 70),
        ("%B < 0.8 only", lambda t: t.get("bb_pct_b", 0.5) < 0.8),
        ("SMA200 + PDI > MDI", lambda t: t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0)),
        ("SMA200 + ADX > 25", lambda t: t.get("above_sma200", False) and t.get("adx", 0) > 25),
        ("SMA200 + 48h > -2%", lambda t: t.get("above_sma200", False) and t.get("dd48", 0) > -2),
        ("SMA200 + %B 0.2-0.6", lambda t: t.get("above_sma200", False) and 0.2 <= t.get("bb_pct_b", 0.5) < 0.6),
        ("NOT (below SMA200 + PDI <= MDI)", lambda t: not (not t.get("above_sma200", False) and t.get("pdi", 0) <= t.get("mdi", 0))),
        ("SMA200 + PDI>MDI + ADX>25", lambda t: t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0) and t.get("adx", 0) > 25),
    ]
    
    print(f"\n{'Filter':40s} {'Trades':>6s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s} {'Compound':>9s}")
    print("-" * 95)
    
    for label, condition_fn in filters:
        subset = [t for t in trades if condition_fn(t)]
        if not subset:
            continue
        m = compute_metrics(subset)
        print(f"{label:40s} {m['trades']:>6d} {m['sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['win_rate']:>5.1f}% {m['pf']:>5.2f} {m['max_dd']:>+7.1f}% {m['compound']:>+8.1f}%")
    
    # ========================================================================
    # PART 5: WALK-FORWARD VALIDATION (Baseline + Best Filters)
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 5: WALK-FORWARD VALIDATION")
    print("=" * 70)
    
    # Baseline walk-forward
    print("\n--- Baseline (no filter) ---")
    wf_baseline = walk_forward_analysis(df, signals, baseline_params)
    wf_positive = 0
    total_wf_sum = 0
    all_sharpes = []
    for r in wf_baseline:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        total_wf_sum += r["sum"]
        all_sharpes.append(r["sharpe"])
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  OOS Profitable: {wf_positive}/{len(wf_baseline)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # SMA200 filter walk-forward
    print("\n--- SMA200 Filter ---")
    sma200_sig = signals & (df["close"] > df["sma200"])
    wf_sma200 = walk_forward_analysis(df, sma200_sig, baseline_params)
    wf_positive = 0
    total_wf_sum = 0
    all_sharpes = []
    for r in wf_sma200:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        total_wf_sum += r["sum"]
        all_sharpes.append(r["sharpe"])
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  OOS Profitable: {wf_positive}/{len(wf_sma200)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # PDI>MDI filter walk-forward
    print("\n--- PDI > MDI Filter ---")
    pdi_sig = signals & (df["pdi"] > df["mdi"])
    wf_pdi = walk_forward_analysis(df, pdi_sig, baseline_params)
    wf_positive = 0
    total_wf_sum = 0
    all_sharpes = []
    for r in wf_pdi:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        total_wf_sum += r["sum"]
        all_sharpes.append(r["sharpe"])
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  OOS Profitable: {wf_positive}/{len(wf_pdi)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # SMA200 + PDI>MDI
    print("\n--- SMA200 + PDI > MDI (BEST COMBO) ---")
    best_sig = signals & (df["close"] > df["sma200"]) & (df["pdi"] > df["mdi"])
    wf_best = walk_forward_analysis(df, best_sig, baseline_params)
    wf_positive = 0
    total_wf_sum = 0
    all_sharpes = []
    for r in wf_best:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        total_wf_sum += r["sum"]
        all_sharpes.append(r["sharpe"])
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  OOS Profitable: {wf_positive}/{len(wf_best)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # 48h > -2% filter (robustness)
    print("\n--- 48h > -2% Filter ---")
    dd48_sig = signals & (df["dd48"] > -2)
    wf_dd48 = walk_forward_analysis(df, dd48_sig, baseline_params)
    wf_positive = 0
    total_wf_sum = 0
    all_sharpes = []
    for r in wf_dd48:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        total_wf_sum += r["sum"]
        all_sharpes.append(r["sharpe"])
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    print(f"  OOS Profitable: {wf_positive}/{len(wf_dd48)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(all_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")
    
    # ========================================================================
    # PART 6: EXIT OPTIMIZATION WITH BEST FILTER
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 6: EXIT OPTIMIZATION (SMA200 + PDI>MDI filter)")
    print("=" * 70)
    
    # Generate filtered trades with different exit params
    best_sig_series = signals & (df["close"] > df["sma200"]) & (df["pdi"] > df["mdi"])
    
    # Sweep stop
    print("\n--- Stop Loss Sweep (target=5.0%, hold=24h) ---")
    print(f"{'Stop':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s}")
    print("-" * 55)
    for sl in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        params = {**baseline_params, "stop_pct": sl}
        t = regime_backtest(df, best_sig_series, {}, **params)
        if t:
            m = compute_metrics(t)
            print(f"{sl:>7.1f}% {m['trades']:>7d} {m['sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['win_rate']:>5.1f}% {m['pf']:>5.2f} {m['max_dd']:>+7.1f}%")
    
    # Sweep target
    print("\n--- Take Profit Sweep (stop=3.0%, hold=24h) ---")
    print(f"{'Target':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s}")
    print("-" * 55)
    for tp in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]:
        params = {**baseline_params, "target_pct": tp}
        t = regime_backtest(df, best_sig_series, {}, **params)
        if t:
            m = compute_metrics(t)
            print(f"{tp:>7.1f}% {m['trades']:>7d} {m['sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['win_rate']:>5.1f}% {m['pf']:>5.2f} {m['max_dd']:>+7.1f}%")
    
    # Sweep hold
    print("\n--- Hold Time Sweep (stop=3.0%, target=5.0%) ---")
    print(f"{'Hold':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s}")
    print("-" * 55)
    for hh in [4, 6, 8, 10, 12, 16, 20, 24, 32, 48]:
        params = {**baseline_params, "max_hold": hh}
        t = regime_backtest(df, best_sig_series, {}, **params)
        if t:
            m = compute_metrics(t)
            print(f"{hh:>7d}h {m['trades']:>7d} {m['sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['win_rate']:>5.1f}% {m['pf']:>5.2f} {m['max_dd']:>+7.1f}%")
    
    # ========================================================================
    # PART 7: MFE/MAE ANALYSIS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 7: MFE/MAE ANALYSIS")
    print("=" * 70)
    
    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    
    print(f"\n  Max Favorable Excursion (MFE):")
    print(f"    Mean:   {np.mean(mfes):+.2f}%")
    print(f"    Median: {np.median(mfes):+.2f}%")
    print(f"    Max:    {np.max(mfes):+.2f}%")
    print(f"    Std:    {np.std(mfes):.2f}%")
    
    print(f"\n  Max Adverse Excursion (MAE):")
    print(f"    Mean:   {np.mean(maes):+.2f}%")
    print(f"    Median: {np.median(maes):+.2f}%")
    
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
    # PART 8: BINANCE CROSS-VALIDATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 8: BINANCE CROSS-VALIDATION")
    print("=" * 70)
    
    df_b = df_binance.copy()
    df_b["sma200"] = sma(df_b["close"], 200)
    adx_b = adx_func(df_b, 14)
    df_b["pdi"] = adx_b["pdi"]
    df_b["mdi"] = adx_b["mdi"]
    df_b["dd48"] = pct_change_rolling(df_b["close"], 48)
    
    sig_b = spring_signal(df_b, lookback=20, vol_mult=1.5, close_pct=0.5)
    
    # Baseline
    trades_b = regime_backtest(df_b, sig_b, {}, **baseline_params)
    if trades_b:
        m_b = compute_metrics(trades_b)
        print(f"\n  Binance Baseline:")
        print(f"    Trades: {m_b['trades']}, Sum: {m_b['sum']:+.1f}%, Sharpe: {m_b['sharpe']:+.2f}, WR: {m_b['win_rate']:.1f}%, PF: {m_b['pf']:.2f}, MaxDD: {m_b['max_dd']:+.1f}%")
    
    # SMA200 filter
    sig_b_sma200 = sig_b & (df_b["close"] > df_b["sma200"])
    trades_b_sma200 = regime_backtest(df_b, sig_b_sma200, {}, **baseline_params)
    if trades_b_sma200:
        m_b2 = compute_metrics(trades_b_sma200)
        print(f"\n  Binance SMA200 Filter:")
        print(f"    Trades: {m_b2['trades']}, Sum: {m_b2['sum']:+.1f}%, Sharpe: {m_b2['sharpe']:+.2f}, WR: {m_b2['win_rate']:.1f}%, PF: {m_b2['pf']:.2f}, MaxDD: {m_b2['max_dd']:+.1f}%")
    
    # SMA200 + PDI>MDI
    sig_b_best = sig_b & (df_b["close"] > df_b["sma200"]) & (df_b["pdi"] > df_b["mdi"])
    trades_b_best = regime_backtest(df_b, sig_b_best, {}, **baseline_params)
    if trades_b_best:
        m_b3 = compute_metrics(trades_b_best)
        print(f"\n  Binance SMA200 + PDI>MDI:")
        print(f"    Trades: {m_b3['trades']}, Sum: {m_b3['sum']:+.1f}%, Sharpe: {m_b3['sharpe']:+.2f}, WR: {m_b3['win_rate']:.1f}%, PF: {m_b3['pf']:.2f}, MaxDD: {m_b3['max_dd']:+.1f}%")
    
    # Cross-exchange comparison
    print(f"\n  Cross-Exchange Comparison (SMA200 + PDI>MDI):")
    print(f"  {'Metric':20s} {'OKX':>10s} {'Binance':>10s}")
    print(f"  {'-'*42}")
    
    # OKX best filter metrics
    best_trades_okx = [t for t in trades if t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0)]
    m_okx_best = compute_metrics(best_trades_okx)
    
    for key, okx_val, bin_val in [
        ("Sharpe", m_okx_best["sharpe"], m_b3["sharpe"]),
        ("Return (sum)", m_okx_best["sum"], m_b3["sum"]),
        ("Max DD", m_okx_best["max_dd"], m_b3["max_dd"]),
        ("Win Rate", m_okx_best["win_rate"], m_b3["win_rate"]),
        ("Profit Factor", m_okx_best["pf"], m_b3["pf"]),
        ("Trades", m_okx_best["trades"], m_b3["trades"]),
    ]:
        if key in ("Return (sum)", "Max DD"):
            print(f"  {key:20s} {okx_val:>+9.1f}% {bin_val:>+9.1f}%")
        elif key == "Win Rate":
            print(f"  {key:20s} {okx_val:>9.1f}% {bin_val:>9.1f}%")
        elif key == "Trades":
            print(f"  {key:20s} {okx_val:>10d} {bin_val:>10d}")
        else:
            print(f"  {key:20s} {okx_val:>+10.2f} {bin_val:>+10.2f}")
    
    # ========================================================================
    # PART 9: CONSECUTIVE LOSS ANALYSIS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 9: CONSECUTIVE LOSS ANALYSIS")
    print("=" * 70)
    
    # Analyze what happens after consecutive losses
    pnls = [t["pnl_pct"] for t in trades]
    
    # Find streaks
    streaks = []
    current_streak = 0
    for i, p in enumerate(pnls):
        if p <= 0:
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    
    if current_streak > 0:
        streaks.append(current_streak)
    
    print(f"\n  Loss Streak Distribution:")
    streak_counts = Counter(streaks)
    for k in sorted(streak_counts.keys()):
        print(f"    {k} consecutive losses: {streak_counts[k]} occurrences")
    
    # After N consecutive losses, what's the next trade's performance?
    print(f"\n  Next Trade After N Consecutive Losses:")
    for n_losses in [1, 2, 3, 4, 5]:
        next_trades = []
        consec = 0
        for i, p in enumerate(pnls):
            if p <= 0:
                consec += 1
                if consec == n_losses and i + 1 < len(pnls):
                    next_trades.append(pnls[i + 1])
            else:
                consec = 0
        
        if next_trades:
            print(f"    After {n_losses} losses: {len(next_trades)} trades, avg={np.mean(next_trades):+.2f}%, win_rate={sum(1 for x in next_trades if x > 0)/len(next_trades)*100:.1f}%")
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    print(f"\n  Baseline (unfiltered):")
    print(f"    Trades: {m['trades']}, Sharpe: {m['sharpe']:+.2f}, Sum: {m['sum']:+.1f}%, MaxDD: {m['max_dd']:+.1f}%")
    
    # Best filter
    best_subset = [t for t in trades if t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0)]
    m_best = compute_metrics(best_subset)
    print(f"\n  Best Filter (SMA200 + PDI>MDI):")
    print(f"    Trades: {m_best['trades']}, Sharpe: {m_best['sharpe']:+.2f}, Sum: {m_best['sum']:+.1f}%, MaxDD: {m_best['max_dd']:+.1f}%")
    
    print(f"\n  Improvement:")
    print(f"    Sharpe: {m['sharpe']:+.2f} → {m_best['sharpe']:+.2f} ({(m_best['sharpe'] - m['sharpe']) / abs(m['sharpe']) * 100:+.0f}%)" if m['sharpe'] != 0 else "    Sharpe: N/A")
    print(f"    MaxDD:  {m['max_dd']:+.1f}% → {m_best['max_dd']:+.1f}%")
    print(f"    Sum:    {m['sum']:+.1f}% → {m_best['sum']:+.1f}%")
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
