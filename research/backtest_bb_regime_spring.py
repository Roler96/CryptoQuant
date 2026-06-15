"""
BB Breakout Regime → Spring Reversal Entries
=============================================

Hypothesis: BB Breakout (close > upper BB 50,2.5) identifies strong momentum
uptrends better than static SMA200. Spring reversals within a recent BB Breakout
regime should be higher quality than those filtered by SMA200 alone.

This tests using BB Breakout as a DYNAMIC regime filter for Spring entries,
replacing the static SMA200 + BB %B 0.2-0.6 filter with a more responsive
"regime window" approach.

Key research questions:
1. Does BB Breakout regime filtering produce more trades than SMA200+BB filter?
2. Does it maintain or improve risk-adjusted returns?
3. Which regime window (24h, 48h, 72h, 120h) works best?
4. Does combining BB regime with BB %B zone filter improve further?
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import (
    sma, bollinger_bands, adx as adx_func,
    atr as atr_func, rsi, pct_change_rolling,
)


# ============================================================================
# Spring Reversal Signal
# ============================================================================

def spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5):
    """Detect Wyckoff Spring reversal pattern."""
    opens = df["open"]
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    volumes = df["volume"]

    rolling_low = lows.rolling(lookback).min().shift(1)
    new_low = lows < rolling_low

    bullish_close = closes > opens

    bar_range = highs - lows
    close_position = (closes - lows) / bar_range.replace(0, np.nan)
    close_near_high = close_position > close_pct

    avg_vol = volumes.rolling(lookback).mean().shift(1)
    high_volume = volumes > (vol_mult * avg_vol)

    return new_low & bullish_close & close_near_high & high_volume


# ============================================================================
# BB Breakout Signal (for regime detection)
# ============================================================================

def bb_breakout_signal(df, bb_period=50, bb_std=2.5):
    """Detect BB upper band breakout — momentum regime indicator."""
    close = df["close"]
    bb = bollinger_bands(df, period=bb_period, std=bb_std)
    return close > bb["upper"]


# ============================================================================
# BB Breakout Regime Filter
# ============================================================================

def bb_regime_filter(df, bb_period=50, bb_std=2.5, regime_window=72):
    """
    Create a regime mask: True if a BB Breakout has occurred within
    the last `regime_window` bars.
    
    The BB Breakout is a momentum signal that persists for some time.
    Spring reversals within this regime are "pullbacks in uptrends".
    """
    breakout = bb_breakout_signal(df, bb_period, bb_std)
    # Rolling max: True if ANY breakout in last N bars
    regime = breakout.rolling(regime_window, min_periods=1).max().fillna(0).astype(bool)
    return regime


# ============================================================================
# Custom Backtest with Regime Tagging
# ============================================================================

def regime_backtest(df, signals, regime_data, stop_pct=3.0, target_pct=5.0,
                    max_hold=24, commission=0.0005, slippage=0.0005):
    """Run backtest and tag each trade with regime data at entry time."""
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)

    trades = []
    position = None
    pending_signal = False

    for i in range(n):
        # Enter position
        if position is None and pending_signal:
            entry_price = opens[i]
            entry_idx = i
            stop_price = entry_price * (1 - stop_pct / 100)
            target_price = entry_price * (1 + target_pct / 100)

            position = {
                "entry_idx": entry_idx,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "max_hold": max_hold,
                "bars_held": 0,
                "high_since_entry": entry_price,
                "low_since_entry": entry_price,
            }
            pending_signal = False
            continue

        # Check signal for next bar entry
        if position is None and signals.iloc[i] == 1:
            pending_signal = True

        # Manage position
        if position is not None:
            position["bars_held"] += 1
            position["high_since_entry"] = max(position["high_since_entry"], highs[i])
            position["low_since_entry"] = min(position["low_since_entry"], lows[i])

            exit_reason = None
            exit_price = None

            # Priority 1: Stop loss (check against low)
            if lows[i] <= position["stop_price"]:
                exit_reason = "stop_loss"
                exit_price = position["stop_price"] * (1 - slippage)

            # Priority 2: Take profit (check against high)
            elif highs[i] >= position["target_price"]:
                exit_reason = "take_profit"
                exit_price = position["target_price"] * (1 - slippage)

            # Priority 3: Time exit
            elif position["bars_held"] >= position["max_hold"]:
                exit_reason = "time_exit"
                exit_price = closes[i]

            # Priority 4: Signal reversal
            elif signals.iloc[i] == -1:
                exit_reason = "signal_reverse"
                exit_price = closes[i]

            if exit_reason is not None:
                pnl_pct = (exit_price / position["entry_price"] - 1) * 100
                pnl_pct -= commission * 100  # round-trip commission

                mfe_pct = (position["high_since_entry"] / position["entry_price"] - 1) * 100
                mae_pct = (position["low_since_entry"] / position["entry_price"] - 1) * 100

                # Get regime data at entry
                entry_regime = {}
                for key, arr in regime_data.items():
                    if key in df.columns:
                        entry_regime[key] = df[key].iloc[position["entry_idx"]]
                    elif isinstance(arr, np.ndarray):
                        entry_regime[key] = arr[position["entry_idx"]]
                    elif isinstance(arr, pd.Series):
                        entry_regime[key] = arr.iloc[position["entry_idx"]]

                trade = {
                    "entry_idx": position["entry_idx"],
                    "exit_idx": i,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "exit_reason": exit_reason,
                    "bars_held": position["bars_held"],
                    **entry_regime,
                }
                trades.append(trade)
                position = None
                pending_signal = False

    return trades


# ============================================================================
# Metrics Calculation
# ============================================================================

def compute_metrics(trades, df):
    """Compute comprehensive backtest metrics."""
    if not trades:
        return {
            "trades": 0, "total_sum": 0, "compound_return": 0,
            "annualized": 0, "sharpe": 0, "sortino": 0,
            "max_dd": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0,
            "profit_factor": 0, "max_consec": 0,
            "exit_breakdown": {}, "mfes": [], "maes": [],
        }

    pnls = [t["pnl_pct"] for t in trades]
    total_sum = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0

    downside = [p for p in pnls if p < 0]
    sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if downside and len(pnls) > 1 and np.std(downside) > 0 else 0

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
    annualized = ((1 + compound_return / 100) ** (1 / years) - 1) * 100 if compound_return > -100 else -100

    exit_counts = Counter(t["exit_reason"] for t in trades)

    # Exit breakdown with PnL details
    exit_detail = {}
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t["exit_reason"] == reason]
        if subset:
            sp = [t["pnl_pct"] for t in subset]
            exit_detail[reason] = {
                "count": len(subset),
                "pct": len(subset) / len(trades) * 100,
                "avg": np.mean(sp),
                "total": sum(sp),
            }

    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]

    return {
        "trades": len(trades),
        "total_sum": total_sum,
        "compound_return": compound_return,
        "annualized": annualized,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": pf,
        "max_consec": max_consec,
        "exit_breakdown": exit_detail,
        "mfes": mfes,
        "maes": maes,
        "trades_list": trades,
    }


# ============================================================================
# Walk-Forward
# ============================================================================

def walk_forward(df, signal_series, n_splits=7, **kwargs):
    """Run walk-forward validation on a pre-computed signal series."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        split_sig = signal_series.iloc[start:end]

        trades = regime_backtest(split_df, split_sig, {}, **kwargs)

        if trades:
            pnls = [t["pnl_pct"] for t in trades]
            total_sum = sum(pnls)
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
            dd_curve = [10000]
            for p in pnls:
                dd_curve.append(dd_curve[-1] * (1 + p / 100))
            dd_curve = np.array(dd_curve)
            peak = np.maximum.accumulate(dd_curve)
            dd = (dd_curve - peak) / peak * 100
            max_dd = dd.min()
        else:
            total_sum = 0
            sharpe = 0
            max_dd = 0

        results.append({
            "split": s + 1,
            "start": split_df.index[0],
            "end": split_df.index[-1],
            "trades": len(trades) if trades else 0,
            "sum": total_sum,
            "sharpe": sharpe,
            "max_dd": max_dd,
        })

    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("BB BREAKOUT REGIME → SPRING REVERSAL ENTRIES")
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

    # SMA
    df["sma200"] = sma(df["close"], 200)
    df["sma50"] = sma(df["close"], 50)

    # ADX
    adx_df = adx_func(df, 14)
    df["adx"] = adx_df["adx"]
    df["pdi"] = adx_df["pdi"]
    df["mdi"] = adx_df["mdi"]

    # ATR
    df["atr14"] = atr_func(df, 14)
    df["median_atr200"] = df["atr14"].rolling(200).median()
    df["vol_ratio"] = df["atr14"] / df["median_atr200"]

    # RSI
    df["rsi14"] = rsi(df["close"], 14)

    # Price changes
    df["dd48"] = pct_change_rolling(df["close"], 48)

    # BB %B (standard 20,2.0 for Spring filter)
    bb_std = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb_std["pct_b"]

    # BB Breakout (50,2.5 for regime detection)
    bb_wide = bollinger_bands(df, 50, 2.5)
    df["bb_upper_wide"] = bb_wide["upper"]
    df["bb_middle_wide"] = bb_wide["middle"]
    df["bb_lower_wide"] = bb_wide["lower"]
    df["bb_breakout"] = (df["close"] > df["bb_upper_wide"]).astype(int)

    # Core Spring signal
    spring_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)

    # ========================================================================
    # BASELINE 1: Spring with SMA200 + BB %B 0.2-0.6 (current best)
    # ========================================================================
    print("\n" + "=" * 70)
    print("BASELINE 1: Spring + SMA200 + BB %B 0.2-0.6")
    print("=" * 70)

    bb_zone_filter = (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)
    sma200_filter = df["close"] > df["sma200"]
    baseline_sig = spring_sig & bb_zone_filter & sma200_filter

    print(f"  Spring signals:           {spring_sig.sum()}")
    print(f"  After BB %B 0.2-0.6:      {(spring_sig & bb_zone_filter).sum()}")
    print(f"  After SMA200:              {(spring_sig & sma200_filter).sum()}")
    print(f"  After BOTH filters:        {baseline_sig.sum()}")

    base_params = {"stop_pct": 3.0, "target_pct": 2.5, "max_hold": 24,
                   "commission": 0.0005, "slippage": 0.0005}
    
    regime_data = {
        "above_sma200": (df["close"] > df["sma200"]).values,
        "adx": df["adx"].values,
        "pdi": df["pdi"].values,
        "mdi": df["mdi"].values,
        "vol_ratio": df["vol_ratio"].values,
        "rsi14": df["rsi14"].values,
        "dd48": df["dd48"].values,
        "bb_pct_b": df["bb_pct_b"].values,
        "bb_breakout": df["bb_breakout"].values,
    }

    trades_baseline = regime_backtest(df, baseline_sig, regime_data, **base_params)
    metrics_baseline = compute_metrics(trades_baseline, df)

    print(f"\n  Trades: {metrics_baseline['trades']}")
    print(f"  Compound Return: {metrics_baseline['compound_return']:+.1f}%")
    print(f"  Sharpe: {metrics_baseline['sharpe']:+.2f}")
    print(f"  Max DD: {metrics_baseline['max_dd']:+.1f}%")
    print(f"  Win Rate: {metrics_baseline['win_rate']:.1f}%")
    print(f"  Profit Factor: {metrics_baseline['profit_factor']:.2f}")

    # ========================================================================
    # BASELINE 2: Spring unfiltered (raw)
    # ========================================================================
    print("\n" + "=" * 70)
    print("BASELINE 2: Spring Unfiltered (raw)")
    print("=" * 70)

    trades_raw = regime_backtest(df, spring_sig, regime_data, **base_params)
    metrics_raw = compute_metrics(trades_raw, df)

    print(f"\n  Trades: {metrics_raw['trades']}")
    print(f"  Compound Return: {metrics_raw['compound_return']:+.1f}%")
    print(f"  Sharpe: {metrics_raw['sharpe']:+.2f}")
    print(f"  Max DD: {metrics_raw['max_dd']:+.1f}%")
    print(f"  Win Rate: {metrics_raw['win_rate']:.1f}%")
    print(f"  Profit Factor: {metrics_raw['profit_factor']:.2f}")

    # ========================================================================
    # TEST 1: BB Breakout Regime Filter (various windows)
    # ========================================================================
    print("\n" + "=" * 70)
    print("TEST 1: BB BREAKOUT REGIME FILTER (Window Sweep)")
    print("=" * 70)

    regime_windows = [24, 48, 72, 96, 120, 168]
    
    print(f"\n{'Window':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'TP%':>6s} {'SL%':>6s} {'TE%':>6s}")
    print("-" * 85)

    best_regime_result = None
    best_regime_sharpe = -999
    best_regime_window = None
    best_regime_sig = None

    for window in regime_windows:
        # BB Breakout regime: True if breakout in last `window` bars
        bb_regime = bb_regime_filter(df, bb_period=50, bb_std=2.5, regime_window=window)
        regime_sig = spring_sig & bb_regime
        
        trades = regime_backtest(df, regime_sig, regime_data, **base_params)
        m = compute_metrics(trades, df)
        
        tp_pct = m["exit_breakdown"].get("take_profit", {}).get("pct", 0)
        sl_pct = m["exit_breakdown"].get("stop_loss", {}).get("pct", 0)
        te_pct = m["exit_breakdown"].get("time_exit", {}).get("pct", 0)

        print(f"  {window:4d}h    {m['trades']:5d}   {m['total_sum']:+7.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['profit_factor']:5.2f}  {tp_pct:5.1f}% {sl_pct:5.1f}% {te_pct:5.1f}%")

        if m["sharpe"] > best_regime_sharpe:
            best_regime_sharpe = m["sharpe"]
            best_regime_result = m
            best_regime_window = window
            best_regime_sig = regime_sig

    print(f"\n  BEST: window={best_regime_window}h, Sharpe={best_regime_sharpe:+.2f}")

    # ========================================================================
    # TEST 2: BB Regime + BB %B Zone (combined)
    # ========================================================================
    print("\n" + "=" * 70)
    print("TEST 2: BB BREAKOUT REGIME + BB %B ZONE FILTER")
    print("=" * 70)

    # Test combining BB regime with the BB %B zone filter (but NO SMA200)
    print(f"\n{'Window':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'TP%':>6s} {'SL%':>6s} {'TE%':>6s}")
    print("-" * 85)

    best_combo_result = None
    best_combo_sharpe = -999
    best_combo_window = None
    best_combo_sig = None

    for window in regime_windows:
        bb_regime = bb_regime_filter(df, bb_period=50, bb_std=2.5, regime_window=window)
        # Combine: BB regime + BB %B 0.2-0.6 (NO SMA200)
        combo_sig = spring_sig & bb_regime & bb_zone_filter
        
        trades = regime_backtest(df, combo_sig, regime_data, **base_params)
        m = compute_metrics(trades, df)
        
        tp_pct = m["exit_breakdown"].get("take_profit", {}).get("pct", 0)
        sl_pct = m["exit_breakdown"].get("stop_loss", {}).get("pct", 0)
        te_pct = m["exit_breakdown"].get("time_exit", {}).get("pct", 0)

        print(f"  {window:4d}h    {m['trades']:5d}   {m['total_sum']:+7.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['profit_factor']:5.2f}  {tp_pct:5.1f}% {sl_pct:5.1f}% {te_pct:5.1f}%")

        if m["sharpe"] > best_combo_sharpe:
            best_combo_sharpe = m["sharpe"]
            best_combo_result = m
            best_combo_window = window
            best_combo_sig = combo_sig

    print(f"\n  BEST: window={best_combo_window}h, Sharpe={best_combo_sharpe:+.2f}")

    # ========================================================================
    # TEST 3: BB Regime + SMA200 (no %B zone)
    # ========================================================================
    print("\n" + "=" * 70)
    print("TEST 3: BB BREAKOUT REGIME + SMA200 (no %B zone)")
    print("=" * 70)

    print(f"\n{'Window':>8s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'TP%':>6s} {'SL%':>6s} {'TE%':>6s}")
    print("-" * 85)

    best_sma_result = None
    best_sma_sharpe = -999
    best_sma_window = None
    best_sma_sig = None

    for window in regime_windows:
        bb_regime = bb_regime_filter(df, bb_period=50, bb_std=2.5, regime_window=window)
        # Combine: BB regime + SMA200 (NO BB %B)
        sma_combo_sig = spring_sig & bb_regime & sma200_filter
        
        trades = regime_backtest(df, sma_combo_sig, regime_data, **base_params)
        m = compute_metrics(trades, df)
        
        tp_pct = m["exit_breakdown"].get("take_profit", {}).get("pct", 0)
        sl_pct = m["exit_breakdown"].get("stop_loss", {}).get("pct", 0)
        te_pct = m["exit_breakdown"].get("time_exit", {}).get("pct", 0)

        print(f"  {window:4d}h    {m['trades']:5d}   {m['total_sum']:+7.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['profit_factor']:5.2f}  {tp_pct:5.1f}% {sl_pct:5.1f}% {te_pct:5.1f}%")

        if m["sharpe"] > best_sma_sharpe:
            best_sma_sharpe = m["sharpe"]
            best_sma_result = m
            best_sma_window = window
            best_sma_sig = sma_combo_sig

    print(f"\n  BEST: window={best_sma_window}h, Sharpe={best_sma_sharpe:+.2f}")

    # ========================================================================
    # TEST 4: Exit optimization on best filter
    # ========================================================================
    print("\n" + "=" * 70)
    print("TEST 4: EXIT OPTIMIZATION ON BEST FILTER")
    print("=" * 70)

    # Use the best filter from above
    best_sig_for_opt = best_regime_sig  # BB regime only, best window
    best_window_for_opt = best_regime_window
    
    print(f"\n  Filter: BB Regime (window={best_window_for_opt}h)")
    print(f"  Signal count: {best_sig_for_opt.sum()}")

    stops = [2.0, 2.5, 3.0, 3.5]
    targets = [1.5, 2.0, 2.5, 3.0]
    holds = [16, 20, 24, 32]

    print(f"\n{'Stop':>6s} {'Target':>7s} {'Hold':>5s} {'Trades':>6s} {'Sum':>7s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 80)

    best_exit_result = None
    best_exit_sharpe = -999
    best_exit_params = None

    for stop in stops:
        for target in targets:
            for hold in holds:
                params = {"stop_pct": stop, "target_pct": target, "max_hold": hold,
                          "commission": 0.0005, "slippage": 0.0005}
                trades = regime_backtest(df, best_sig_for_opt, regime_data, **params)
                m = compute_metrics(trades, df)
                
                if m["sharpe"] > best_exit_sharpe:
                    best_exit_sharpe = m["sharpe"]
                    best_exit_result = m
                    best_exit_params = params

                # Print only interesting ones
                if m["sharpe"] > 1.0:
                    print(f"  {stop:4.1f}%  {target:5.1f}%   {hold:3d}h   {m['trades']:5d}  {m['total_sum']:+7.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['profit_factor']:5.2f}")

    print(f"\n  BEST EXIT: stop={best_exit_params['stop_pct']}%, target={best_exit_params['target_pct']}%, hold={best_exit_params['max_hold']}h")
    print(f"  Sharpe={best_exit_sharpe:+.2f}, Sum={best_exit_result['total_sum']:+.1f}%")

    # ========================================================================
    # DETAILED REPORT: Best Overall Configuration
    # ========================================================================
    print("\n" + "=" * 70)
    print("DETAILED REPORT: BEST OVERALL CONFIGURATION")
    print("=" * 70)

    # Determine the best overall approach
    all_candidates = [
        ("Baseline (SMA200+BB0.2-0.6)", metrics_baseline, base_params),
        ("BB Regime Only", best_regime_result, base_params),
        ("BB Regime + %B Zone", best_combo_result, base_params),
        ("BB Regime + SMA200", best_sma_result, base_params),
        ("BB Regime + Exit Opt", best_exit_result, best_exit_params),
    ]

    # Sort by Sharpe
    all_candidates.sort(key=lambda x: x[1]["sharpe"], reverse=True)

    print(f"\n{'Rank':>4s} {'Strategy':<30s} {'Sharpe':>7s} {'Sum':>8s} {'MaxDD':>7s} {'Trades':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 90)
    for rank, (name, m, params) in enumerate(all_candidates, 1):
        print(f"  {rank:2d}. {name:<30s} {m['sharpe']:+7.2f} {m['total_sum']:+7.1f}% {m['max_dd']:+6.1f}% {m['trades']:6d} {m['win_rate']:5.1f}% {m['profit_factor']:5.2f}")

    # Pick the best
    best_name, best_metrics, best_params_for_report = all_candidates[0]
    best_signal_map = {
        "Baseline (SMA200+BB0.2-0.6)": baseline_sig,
        "BB Regime Only": best_regime_sig,
        "BB Regime + %B Zone": best_combo_sig,
        "BB Regime + SMA200": best_sma_sig,
        "BB Regime + Exit Opt": best_sig_for_opt,
    }
    best_signal = best_signal_map.get(best_name, baseline_sig)
    if best_signal is None:
        best_signal = baseline_sig

    print(f"\n  🏆 BEST: {best_name}")
    print(f"  Params: stop={best_params_for_report['stop_pct']}%, target={best_params_for_report['target_pct']}%, hold={best_params_for_report['max_hold']}h")
    print(f"  Signal count: {best_signal.sum()}")

    # ========================================================================
    # FULL DETAILS for Best Configuration
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"FULL BACKTEST: {best_name}")
    print(f"{'='*55}")

    # Re-run with correct params
    if best_name == "BB Regime + Exit Opt" and best_exit_params is not None:
        best_trades_for_detail = regime_backtest(df, best_sig_for_opt, regime_data, **best_exit_params)
        best_m_for_detail = compute_metrics(best_trades_for_detail, df)
    else:
        best_trades_for_detail = regime_backtest(df, best_signal, regime_data, **base_params)
        best_m_for_detail = compute_metrics(best_trades_for_detail, df)

    print(f"\n  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {best_m_for_detail['trades']}")
    print(f"  Compound Return:    {best_m_for_detail['compound_return']:+.1f}%")
    print(f"  Annualized Return:  {best_m_for_detail['annualized']:+.1f}%")
    print(f"  Linear Sum:         {best_m_for_detail['total_sum']:+.1f}%")
    print(f"  Sharpe Ratio:       {best_m_for_detail['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {best_m_for_detail['sortino']:+.2f}")
    print(f"  Max Drawdown:       {best_m_for_detail['max_dd']:+.1f}%")
    print(f"  Win Rate:           {best_m_for_detail['win_rate']:.1f}%")
    print(f"  Avg Win:            {best_m_for_detail['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {best_m_for_detail['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {best_m_for_detail['profit_factor']:.2f}")
    print(f"  Max Consec Losses:  {best_m_for_detail['max_consec']}")

    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        detail = best_m_for_detail["exit_breakdown"].get(reason)
        if detail:
            print(f"    {reason:15s}: {detail['count']:4d} ({detail['pct']:5.1f}%)  avg={detail['avg']:+.2f}%  total={detail['total']:+.1f}%")

    # MFE/MAE
    print(f"\n  MFE/MAE Analysis:")
    print(f"    MFE  mean={np.mean(best_m_for_detail['mfes']):+.2f}%  median={np.median(best_m_for_detail['mfes']):+.2f}%  max={np.max(best_m_for_detail['mfes']):+.2f}%")
    print(f"    MAE  mean={np.mean(best_m_for_detail['maes']):+.2f}%  median={np.median(best_m_for_detail['maes']):+.2f}%")

    # Time-exit MFE
    time_ex = [t for t in best_trades_for_detail if t["exit_reason"] == "time_exit"]
    if time_ex:
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"    Time-exits profitable at some point: {profitable_time}/{len(time_ex)} ({profitable_time/len(time_ex)*100:.1f}%)")

    # ========================================================================
    # REGIME ANALYSIS for Best Configuration
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"REGIME ANALYSIS: {best_name}")
    print(f"{'='*55}")

    # PDI/MDI
    pdi_above = [t for t in best_trades_for_detail if t.get("pdi", 0) > t.get("mdi", 0)]
    pdi_below = [t for t in best_trades_for_detail if t.get("pdi", 0) <= t.get("mdi", 0)]
    for label, subset in [("PDI > MDI", pdi_above), ("PDI <= MDI", pdi_below)]:
        if subset:
            p = [t["pnl_pct"] for t in subset]
            ss = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:20s}: {len(subset):4d} trades  sum={ss:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")

    # ADX
    for threshold, label in [(25, "ADX > 25 (strong)"), (20, "ADX <= 20 (weak/ranging)")]:
        if ">" in label:
            subset = [t for t in best_trades_for_detail if t.get("adx", 0) > threshold]
        else:
            subset = [t for t in best_trades_for_detail if t.get("adx", 0) <= threshold]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            ss = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={ss:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")

    # Vol ratio
    for low, high, label in [
        (0, 0.8, "Low Vol (<0.8)"),
        (0.8, 1.2, "Normal Vol (0.8-1.2)"),
        (1.2, 10, "High Vol (>1.2)"),
    ]:
        subset = [t for t in best_trades_for_detail if low <= t.get("vol_ratio", 1.0) < high]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            ss = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 and np.std(p) > 0 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={ss:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")

    # ========================================================================
    # WALK-FORWARD: Best Configuration
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"WALK-FORWARD VALIDATION (7 splits)")
    print(f"{'='*55}")

    if best_name == "BB Regime + Exit Opt":
        wf_sig = best_sig_for_opt
        wf_params = best_exit_params if best_exit_params is not None else base_params
    else:
        wf_sig = best_signal
        wf_params = base_params

    wf_results = walk_forward(df, wf_sig, n_splits=7, **wf_params)

    wf_positive = 0
    wf_sharpes = []
    total_wf_sum = 0
    for r in wf_results:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            wf_positive += 1
        wf_sharpes.append(r["sharpe"])
        total_wf_sum += r["sum"]
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+6.1f}%  sharpe={r['sharpe']:+6.2f}  dd={r['max_dd']:+5.1f}%  {status}")

    print(f"\n  OOS Profitable: {wf_positive}/{len(wf_results)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(wf_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")

    # ========================================================================
    # WALK-FORWARD: Baseline for comparison
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"WALK-FORWARD: Baseline (SMA200+BB0.2-0.6)")
    print(f"{'='*55}")

    wf_base = walk_forward(df, baseline_sig, n_splits=7, **base_params)

    base_positive = 0
    base_sharpes = []
    base_total_sum = 0
    for r in wf_base:
        status = "✅" if r["sum"] > 0 else "❌"
        if r["sum"] > 0:
            base_positive += 1
        base_sharpes.append(r["sharpe"])
        base_total_sum += r["sum"]
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+6.1f}%  sharpe={r['sharpe']:+6.2f}  dd={r['max_dd']:+5.1f}%  {status}")

    print(f"\n  OOS Profitable: {base_positive}/{len(wf_base)} splits")
    print(f"  Mean OOS Sharpe: {np.mean(base_sharpes):+.2f}")
    print(f"  Total OOS Sum: {base_total_sum:+.1f}%")

    # ========================================================================
    # COMPARISON TABLE
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"FINAL COMPARISON: Best BB Regime vs Baseline")
    print(f"{'='*55}")

    if best_name == "BB Regime + Exit Opt":
        best_final = best_m_for_detail
    else:
        best_final = compute_metrics(
            regime_backtest(df, best_signal, regime_data, **base_params), df
        )

    print(f"\n  {'Metric':20s} {'Baseline':>12s} {'BB Regime':>12s} {'Delta':>12s}")
    print(f"  {'-'*58}")

    comparisons = [
        ("Trades", metrics_baseline["trades"], best_final["trades"], ""),
        ("Sharpe", metrics_baseline["sharpe"], best_final["sharpe"], "+.2f"),
        ("Compound Return", metrics_baseline["compound_return"], best_final["compound_return"], "+.1f%%"),
        ("Max Drawdown", metrics_baseline["max_dd"], best_final["max_dd"], "+.1f%%"),
        ("Win Rate", metrics_baseline["win_rate"], best_final["win_rate"], ".1f%%"),
        ("Profit Factor", metrics_baseline["profit_factor"], best_final["profit_factor"], ".2f"),
        ("WF Profitable", f"{base_positive}/{len(wf_base)}", f"{wf_positive}/{len(wf_results)}", ""),
        ("Mean WF Sharpe", np.mean(base_sharpes), np.mean(wf_sharpes), "+.2f"),
    ]

    for label, base_val, best_val, fmt in comparisons:
        if isinstance(base_val, float):
            if "%%" in fmt:
                print(f"  {label:20s} {base_val:>+11.1f}% {best_val:>+11.1f}% {best_val - base_val:>+11.1f}%")
            elif fmt == "+.2f":
                print(f"  {label:20s} {base_val:>+11.2f} {best_val:>+11.2f} {best_val - base_val:>+11.2f}")
            elif fmt == ".1f%%":
                print(f"  {label:20s} {base_val:>11.1f}% {best_val:>11.1f}% {best_val - base_val:>+11.1f}%")
            else:
                print(f"  {label:20s} {base_val:>+11.2f} {best_val:>+11.2f} {best_val - base_val:>+11.2f}")
        else:
            print(f"  {label:20s} {str(base_val):>12s} {str(best_val):>12s}")

    # ========================================================================
    # OVERLAP ANALYSIS
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"SIGNAL OVERLAP ANALYSIS")
    print(f"{'='*55}")

    bb_only = (spring_sig & bb_regime_filter(df, 50, 2.5, 72)).sum()
    base_only = baseline_sig.sum()
    overlap = (spring_sig & bb_regime_filter(df, 50, 2.5, 72) & baseline_sig).sum()
    combined_unique = (spring_sig & (bb_regime_filter(df, 50, 2.5, 72) | baseline_sig)).sum()

    print(f"  BB Regime signals:     {bb_only}")
    print(f"  Baseline signals:      {base_only}")
    print(f"  Overlap:               {overlap} ({overlap/max(base_only,1)*100:.1f}% of baseline)")
    print(f"  Combined unique:        {combined_unique}")

    print("\n" + "=" * 70)
    print("RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
