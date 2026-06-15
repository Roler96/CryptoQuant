"""
Spring Reversal — Wyckoff Spring Strategy: Research & Optimization
===================================================================

The Spring Reversal detects "failed breakdowns" — price makes a new low below
recent support but closes bullish with high volume, trapping sellers.

Signal Logic:
1. new_low: current low < lowest low of previous N bars (breakdown)
2. bullish_close: close > open (buyers stepped in)
3. close_near_high: close in upper half of the bar (buyers in control)
4. high_volume: volume > 1.5x 20-bar average (confirmation)
5. Entry when ALL conditions met

This is a Wyckoff Spring pattern — a classic reversal signal.

Research Agenda:
1. Implement signal and baseline backtest
2. Parameter sweep: lookback, volume multiplier, close position threshold
3. Exit optimization: stop, target, hold
4. Regime analysis: SMA200, ADX, PDI/MDI, volatility, RSI
5. Walk-forward validation (6-7 splits)
6. SMA200 filter impact
7. Consecutive loss cooldown mechanism
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, ema, atr as atr_func, adx as adx_func,
    wick_imbalance, pct_change_rolling, rsi, bollinger_bands
)


# ============================================================================
# Spring Reversal Signal Function
# ============================================================================

def spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5):
    """
    Detect Wyckoff Spring reversal pattern.
    
    Conditions:
    1. New low: low[i] < min(low[i-lookback:i]) — breakdown below recent support
    2. Bullish close: close[i] > open[i] — buyers stepped in
    3. Close near high: close is in upper close_pct of the bar range
    4. High volume: volume[i] > vol_mult * avg_volume[i-lookback:i]
    
    Returns boolean Series.
    """
    opens = df["open"]
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    volumes = df["volume"]
    
    # Condition 1: New low (breakdown)
    rolling_low = lows.rolling(lookback).min().shift(1)
    new_low = lows < rolling_low
    
    # Condition 2: Bullish close
    bullish_close = closes > opens
    
    # Condition 3: Close in upper portion of bar
    bar_range = highs - lows
    close_position = (closes - lows) / bar_range.replace(0, np.nan)
    close_near_high = close_position > close_pct
    
    # Condition 4: High volume
    avg_vol = volumes.rolling(lookback).mean().shift(1)
    high_volume = volumes > (vol_mult * avg_vol)
    
    signal = new_low & bullish_close & close_near_high & high_volume
    return signal


# ============================================================================
# Custom backtest with regime tagging
# ============================================================================

def regime_backtest(df, signals, regime_data, stop_pct=3.0, target_pct=5.0,
                    max_hold=24, commission=0.0005, slippage=0.0005):
    """
    Run backtest and tag each trade with regime data at entry time.
    Uses lows for stop checking.
    """
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
            
            # Priority 4: Signal reversal (opposite signal)
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
# Walk-Forward Validation
# ============================================================================

def walk_forward(df, signal_func, n_splits=6, **kwargs):
    """Run walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        
        signals = signal_func(split_df)
        trades = regime_backtest(split_df, signals, {}, **kwargs)
        
        if trades:
            pnls = [t["pnl_pct"] for t in trades]
            total_sum = sum(pnls)
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 else 0
        else:
            total_sum = 0
            sharpe = 0
        
        results.append({
            "split": s + 1,
            "start": split_df.index[0],
            "end": split_df.index[-1],
            "trades": len(trades),
            "sum": total_sum,
            "sharpe": sharpe,
        })
    
    return results


# ============================================================================
# Main Research
# ============================================================================

def main():
    print("=" * 70)
    print("SPRING REVERSAL — COMPREHENSIVE RESEARCH")
    print("=" * 70)
    
    # Load data
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    print(f"\nOKX data: {len(df_okx)} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance data: {len(df_binance)} bars, {df_binance.index[0]} to {df_binance.index[-1]}")
    
    # ========================================================================
    # PART 1: BASELINE BACKTEST
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 1: BASELINE BACKTEST")
    print("=" * 70)
    
    # Compute regime indicators
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
    df["dd168"] = pct_change_rolling(df["close"], 168)
    
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]
    
    # Generate signals
    signals = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    signal_count = signals.sum()
    print(f"\nSignal count: {signal_count}")
    
    # Regime data dict
    regime_data = {
        "above_sma200": (df["close"] > df["sma200"]).values,
        "above_sma50": (df["close"] > df["sma50"]).values,
        "adx": df["adx"].values,
        "pdi": df["pdi"].values,
        "mdi": df["mdi"].values,
        "vol_ratio": df["vol_ratio"].values,
        "rsi14": df["rsi14"].values,
        "dd48": df["dd48"].values,
        "dd168": df["dd168"].values,
        "bb_pct_b": df["bb_pct_b"].values,
    }
    
    # Baseline parameters
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
    
    pnls = [t["pnl_pct"] for t in trades]
    total_sum = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) * 100
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 else 0
    
    # Sortino
    downside = [p for p in pnls if p < 0]
    sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if downside and len(pnls) > 1 else 0
    
    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 1
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    # Max consecutive losses
    max_consec = 0
    consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    
    # Compound return
    compound = 1.0
    for p in pnls:
        compound *= (1 + p / 100)
    compound_return = (compound - 1) * 100
    
    # Max drawdown from equity curve
    equity = [10000]
    for p in pnls:
        equity.append(equity[-1] * (1 + p / 100))
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    max_dd = dd.min()
    
    # Annualized return
    years = (df.index[-1] - df.index[0]).days / 365.25
    annualized = ((1 + compound_return / 100) ** (1 / years) - 1) * 100
    
    # Exit breakdown
    exit_counts = Counter(t["exit_reason"] for t in trades)
    exit_stats = {}
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t["exit_reason"] == reason]
        if subset:
            exit_stats[reason] = {
                "count": len(subset),
                "pct": len(subset) / len(trades) * 100,
                "avg_pnl": np.mean([t["pnl_pct"] for t in subset]),
                "total_pnl": sum(t["pnl_pct"] for t in subset),
            }
    
    print(f"\n{'='*50}")
    print(f"BASELINE RESULTS (OKX BTC/USDT 1h, 2019-2026)")
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
        if reason in exit_stats:
            s = exit_stats[reason]
            print(f"    {reason:15s}: {s['count']:4d} ({s['pct']:5.1f}%)  avg={s['avg_pnl']:+.2f}%  total={s['total_pnl']:+.1f}%")
    
    # ========================================================================
    # PART 2: PARAMETER SWEEP
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 2: PARAMETER SWEEP")
    print("=" * 70)
    
    # Sweep lookback
    print("\n--- Lookback Period Sweep ---")
    print(f"{'Lookback':>10} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print("-" * 60)
    for lb in [5, 10, 15, 20, 25, 30, 40, 50]:
        sig = spring_signal(df, lookback=lb, vol_mult=1.5, close_pct=0.5)
        t = regime_backtest(df, sig, {}, **baseline_params)
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
            print(f"{lb:>10} {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # Sweep volume multiplier
    print("\n--- Volume Multiplier Sweep (lookback=20) ---")
    print(f"{'VolMult':>10} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print("-" * 60)
    for vm in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]:
        sig = spring_signal(df, lookback=20, vol_mult=vm, close_pct=0.5)
        t = regime_backtest(df, sig, {}, **baseline_params)
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
            print(f"{vm:>10.1f} {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # Sweep close position
    print("\n--- Close Position Threshold Sweep (lookback=20, vol_mult=1.5) ---")
    print(f"{'ClosePct':>10} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print("-" * 60)
    for cp in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=cp)
        t = regime_backtest(df, sig, {}, **baseline_params)
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
            print(f"{cp:>10.1f} {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # ========================================================================
    # PART 3: EXIT OPTIMIZATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 3: EXIT OPTIMIZATION")
    print("=" * 70)
    
    # Use best signal params from sweep
    best_lookback = 20
    best_vol_mult = 1.5
    best_close_pct = 0.5
    
    best_sig = spring_signal(df, lookback=best_lookback, vol_mult=best_vol_mult, close_pct=best_close_pct)
    
    # Sweep stop
    print("\n--- Stop Loss Sweep ---")
    print(f"{'Stop':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print("-" * 60)
    for sl in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]:
        params = {**baseline_params, "stop_pct": sl}
        t = regime_backtest(df, best_sig, {}, **params)
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
            print(f"{sl:>7.1f}% {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # Sweep target
    print("\n--- Take Profit Sweep ---")
    print(f"{'Target':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print("-" * 60)
    for tp in [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 10.0]:
        params = {**baseline_params, "target_pct": tp}
        t = regime_backtest(df, best_sig, {}, **params)
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
            print(f"{tp:>7.1f}% {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # Sweep hold
    print("\n--- Hold Time Sweep ---")
    print(f"{'Hold':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>7} {'WR':>6} {'PF':>6} {'MaxDD':>7}")
    print("-" * 60)
    for hh in [4, 6, 8, 10, 12, 16, 20, 24, 32, 48]:
        params = {**baseline_params, "max_hold": hh}
        t = regime_backtest(df, best_sig, {}, **params)
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
            print(f"{hh:>7}h {len(t):>7} {s:>+8.1f}% {sh:>+7.2f} {wr:>5.1f}% {pf_val:>5.2f} {dd_val:>+7.1f}%")
    
    # ========================================================================
    # PART 4: REGIME ANALYSIS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 4: REGIME ANALYSIS")
    print("=" * 70)
    
    # Use baseline trades with regime tags
    print("\n--- SMA200 Regime ---")
    above = [t for t in trades if t.get("above_sma200", False)]
    below = [t for t in trades if not t.get("above_sma200", False)]
    for label, subset in [("Above SMA200", above), ("Below SMA200", below)]:
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            w = [x for x in p if x > 0]
            l = [x for x in p if x <= 0]
            pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
            print(f"  {label:20s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%  pf={pf_val:.2f}")
    
    print("\n--- PDI vs MDI ---")
    pdi_above = [t for t in trades if t.get("pdi", 0) > t.get("mdi", 0)]
    pdi_below = [t for t in trades if t.get("pdi", 0) <= t.get("mdi", 0)]
    for label, subset in [("PDI > MDI", pdi_above), ("PDI <= MDI", pdi_below)]:
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            w = [x for x in p if x > 0]
            l = [x for x in p if x <= 0]
            pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
            print(f"  {label:20s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%  pf={pf_val:.2f}")
    
    print("\n--- ADX Trend Strength ---")
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
            w = [x for x in p if x > 0]
            l = [x for x in p if x <= 0]
            pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%  pf={pf_val:.2f}")
    
    print("\n--- RSI(14) Regime ---")
    for low, high, label in [
        (0, 30, "RSI < 30 (oversold)"),
        (30, 40, "RSI 30-40"),
        (40, 50, "RSI 40-50"),
        (50, 60, "RSI 50-60"),
        (60, 70, "RSI 60-70"),
        (70, 100, "RSI > 70 (overbought)"),
    ]:
        subset = [t for t in trades if low <= t.get("rsi14", 50) < high]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    print("\n--- 48h Price Change ---")
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
    
    print("\n--- Volatility Regime (ATR ratio) ---")
    for low, high, label in [
        (0, 0.7, "Very Low (<0.7)"),
        (0.7, 1.0, "Low (0.7-1.0)"),
        (1.0, 1.5, "Normal (1.0-1.5)"),
        (1.5, 3.0, "High (1.5-3.0)"),
        (3.0, 100, "Very High (>3.0)"),
    ]:
        subset = [t for t in trades if low <= t.get("vol_ratio", 1.0) < high]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    print("\n--- Bollinger %B ---")
    for low, high, label in [
        (0, 0, "<0 (below lower)"),
        (0, 0.2, "0-0.2"),
        (0.2, 0.4, "0.2-0.4"),
        (0.4, 0.6, "0.4-0.6"),
        (0.6, 0.8, "0.6-0.8"),
        (0.8, 1.0, "0.8-1.0"),
        (1.0, 100, ">1.0 (above upper)"),
    ]:
        subset = [t for t in trades if low <= t.get("bb_pct_b", 0.5) < high]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            print(f"  {label:25s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%")
    
    # Combined regimes
    print("\n--- Combined Regimes ---")
    combos = [
        ("Above SMA200 + PDI>MDI", lambda t: t.get("above_sma200", False) and t.get("pdi", 0) > t.get("mdi", 0)),
        ("Below SMA200 + PDI<MDI", lambda t: not t.get("above_sma200", False) and t.get("pdi", 0) <= t.get("mdi", 0)),
        ("Above SMA200 + ADX>25", lambda t: t.get("above_sma200", False) and t.get("adx", 0) > 25),
        ("Below SMA200 + ADX>25", lambda t: not t.get("above_sma200", False) and t.get("adx", 0) > 25),
        ("Above SMA200 + RSI<50", lambda t: t.get("above_sma200", False) and t.get("rsi14", 50) < 50),
        ("Above SMA200 + RSI>=50", lambda t: t.get("above_sma200", False) and t.get("rsi14", 50) >= 50),
    ]
    for label, cond in combos:
        subset = [t for t in trades if cond(t)]
        if subset:
            p = [t["pnl_pct"] for t in subset]
            s = sum(p)
            sh = np.mean(p) / np.std(p) * np.sqrt(len(p)) if len(p) > 1 else 0
            wr = sum(1 for x in p if x > 0) / len(p) * 100
            w = [x for x in p if x > 0]
            l = [x for x in p if x <= 0]
            pf_val = sum(w) / abs(sum(l)) if l and sum(l) != 0 else 0
            stop_rate = sum(1 for t in subset if t["exit_reason"] == "stop_loss") / len(subset) * 100
            print(f"  {label:35s}: {len(subset):4d} trades  sum={s:+.1f}%  sharpe={sh:+.2f}  wr={wr:.1f}%  pf={pf_val:.2f}  stop_rate={stop_rate:.1f}%")
    
    # ========================================================================
    # PART 5: WALK-FORWARD VALIDATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 5: WALK-FORWARD VALIDATION")
    print("=" * 70)
    
    # Baseline walk-forward
    print("\n--- Baseline (no filter) ---")
    wf_results = walk_forward(df, lambda d: spring_signal(d, lookback=20, vol_mult=1.5, close_pct=0.5), **baseline_params)
    for r in wf_results:
        status = "✅" if r["sum"] > 0 else "❌"
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    profitable = sum(1 for r in wf_results if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in wf_results])
    total_oos = sum(r["sum"] for r in wf_results)
    print(f"  OOS Profitable: {profitable}/{len(wf_results)} splits")
    print(f"  Mean OOS Sharpe: {mean_sharpe:+.2f}")
    print(f"  Total OOS Sum: {total_oos:+.1f}%")
    
    # ========================================================================
    # PART 6: SMA200 FILTER IMPACT
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 6: SMA200 FILTER IMPACT")
    print("=" * 70)
    
    # Generate filtered signals
    sma200_filtered = best_sig & (df["close"] > df["sma200"])
    print(f"\nSignal count: {best_sig.sum()} → {sma200_filtered.sum()} (SMA200 filtered)")
    
    filtered_trades = regime_backtest(df, sma200_filtered, regime_data, **baseline_params)
    
    if filtered_trades:
        fp = [t["pnl_pct"] for t in filtered_trades]
        fs = sum(fp)
        fsh = np.mean(fp) / np.std(fp) * np.sqrt(len(fp)) if len(fp) > 1 else 0
        fwr = sum(1 for x in fp if x > 0) / len(fp) * 100
        fw = [x for x in fp if x > 0]
        fl = [x for x in fp if x <= 0]
        fpf = sum(fw) / abs(sum(fl)) if fl and sum(fl) != 0 else 0
        feq = [10000]
        for x in fp:
            feq.append(feq[-1] * (1 + x / 100))
        feq = np.array(feq)
        fdd = (feq - np.maximum.accumulate(feq)).min() / np.maximum.accumulate(feq).max() * 100
        fcompound = (feq[-1] / 10000 - 1) * 100
        
        print(f"\n  SMA200 Filtered Results:")
        print(f"  Total Trades:       {len(filtered_trades)}")
        print(f"  Compound Return:    {fcompound:+.1f}%")
        print(f"  Linear Sum:         {fs:+.1f}%")
        print(f"  Sharpe Ratio:       {fsh:+.2f}")
        print(f"  Win Rate:           {fwr:.1f}%")
        print(f"  Profit Factor:      {fpf:.2f}")
        print(f"  Max Drawdown:       {fdd:+.1f}%")
        
        # Comparison
        print(f"\n  Comparison:")
        print(f"  {'Metric':20s} {'Baseline':>10s} {'SMA200 Filter':>15s} {'Delta':>10s}")
        print(f"  {'-'*55}")
        print(f"  {'Sharpe':20s} {sharpe:>+10.2f} {fsh:>+15.2f} {fsh-sharpe:>+10.2f}")
        print(f"  {'Return (sum)':20s} {total_sum:>+10.1f}% {fs:>+14.1f}% {fs-total_sum:>+10.1f}%")
        print(f"  {'Max DD':20s} {max_dd:>+10.1f}% {fdd:>+14.1f}% {fdd-max_dd:>+10.1f}%")
        print(f"  {'Win Rate':20s} {win_rate:>10.1f}% {fwr:>14.1f}% {fwr-win_rate:>+10.1f}%")
        print(f"  {'Profit Factor':20s} {pf:>10.2f} {fpf:>14.2f} {fpf-pf:>+10.2f}")
        print(f"  {'Trades':20s} {len(trades):>10d} {len(filtered_trades):>15d} {len(filtered_trades)-len(trades):>+10d}")
    
    # SMA200 walk-forward
    print("\n--- SMA200 Filter Walk-Forward ---")
    def sma200_signal_func(d):
        sig = spring_signal(d, lookback=20, vol_mult=1.5, close_pct=0.5)
        s200 = sma(d["close"], 200)
        return sig & (d["close"] > s200)
    
    wf_sma200 = walk_forward(df, sma200_signal_func, **baseline_params)
    for r in wf_sma200:
        status = "✅" if r["sum"] > 0 else "❌"
        print(f"  Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
    profitable_sma200 = sum(1 for r in wf_sma200 if r["sum"] > 0)
    mean_sharpe_sma200 = np.mean([r["sharpe"] for r in wf_sma200])
    total_oos_sma200 = sum(r["sum"] for r in wf_sma200)
    print(f"  OOS Profitable: {profitable_sma200}/{len(wf_sma200)} splits")
    print(f"  Mean OOS Sharpe: {mean_sharpe_sma200:+.2f}")
    print(f"  Total OOS Sum: {total_oos_sma200:+.1f}%")
    
    # ========================================================================
    # PART 7: CONSECUTIVE LOSS COOLDOWN
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 7: CONSECUTIVE LOSS COOLDOWN")
    print("=" * 70)
    
    for cooldown in [0, 1, 2, 3]:
        # Simulate with cooldown
        cooldown_trades = []
        position = None
        pending_signal = False
        loss_streak = 0
        cooldown_remaining = 0
        
        for i in range(len(df)):
            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                continue
            
            if position is None and pending_signal:
                entry_price = df["open"].iloc[i]
                entry_idx = i
                stop_price = entry_price * (1 - baseline_params["stop_pct"] / 100)
                target_price = entry_price * (1 + baseline_params["target_pct"] / 100)
                
                position = {
                    "entry_idx": entry_idx,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "max_hold": baseline_params["max_hold"],
                    "bars_held": 0,
                }
                pending_signal = False
                continue
            
            if position is None and best_sig.iloc[i] == 1:
                pending_signal = True
            
            if position is not None:
                position["bars_held"] += 1
                
                exit_reason = None
                exit_price = None
                
                if df["low"].iloc[i] <= position["stop_price"]:
                    exit_reason = "stop_loss"
                    exit_price = position["stop_price"] * (1 - baseline_params["slippage"])
                elif df["high"].iloc[i] >= position["target_price"]:
                    exit_reason = "take_profit"
                    exit_price = position["target_price"] * (1 - baseline_params["slippage"])
                elif position["bars_held"] >= position["max_hold"]:
                    exit_reason = "time_exit"
                    exit_price = df["close"].iloc[i]
                
                if exit_reason is not None:
                    pnl_pct = (exit_price / position["entry_price"] - 1) * 100
                    pnl_pct -= baseline_params["commission"] * 100
                    
                    cooldown_trades.append({
                        "pnl_pct": pnl_pct,
                        "exit_reason": exit_reason,
                    })
                    
                    if pnl_pct <= 0:
                        loss_streak += 1
                        if loss_streak >= cooldown and cooldown > 0:
                            cooldown_remaining = 24  # skip 24 hours
                    else:
                        loss_streak = 0
                    
                    position = None
                    pending_signal = False
        
        if cooldown_trades:
            cp = [t["pnl_pct"] for t in cooldown_trades]
            cs = sum(cp)
            csh = np.mean(cp) / np.std(cp) * np.sqrt(len(cp)) if len(cp) > 1 else 0
            cwr = sum(1 for x in cp if x > 0) / len(cp) * 100
            ceq = [10000]
            for x in cp:
                ceq.append(ceq[-1] * (1 + x / 100))
            ceq = np.array(ceq)
            cdd = (ceq - np.maximum.accumulate(ceq)).min() / np.maximum.accumulate(ceq).max() * 100
            print(f"  Cooldown={cooldown}: {len(cooldown_trades):4d} trades  sum={cs:+.1f}%  sharpe={csh:+.2f}  wr={cwr:.1f}%  maxdd={cdd:+.1f}%")
    
    # ========================================================================
    # PART 8: BINANCE CROSS-VALIDATION
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 8: BINANCE CROSS-VALIDATION")
    print("=" * 70)
    
    df_b = df_binance.copy()
    sig_b = spring_signal(df_b, lookback=20, vol_mult=1.5, close_pct=0.5)
    trades_b = regime_backtest(df_b, sig_b, {}, **baseline_params)
    
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
        bcompound = (beq[-1] / 10000 - 1) * 100
        
        print(f"\n  Binance Results:")
        print(f"  Total Trades:       {len(trades_b)}")
        print(f"  Compound Return:    {bcompound:+.1f}%")
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
    # PART 9: MFE/MAE ANALYSIS
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 9: MFE/MAE ANALYSIS")
    print("=" * 70)
    
    mfes = [t["mfe_pct"] for t in trades]
    maes = [t["mae_pct"] for t in trades]
    
    print(f"\n  Max Favorable Excursion (MFE):")
    print(f"    Mean:   {np.mean(mfes):+.2f}%")
    print(f"    Median: {np.median(mfes):+.2f}%")
    print(f"    Max:    {np.max(mfes):+.2f}%")
    print(f"    Min:    {np.min(mfes):+.2f}%")
    
    print(f"\n  Max Adverse Excursion (MAE):")
    print(f"    Mean:   {np.mean(maes):+.2f}%")
    print(f"    Median: {np.median(maes):+.2f}%")
    print(f"    Max:    {np.min(maes):+.2f}%")
    print(f"    Min:    {np.max(maes):+.2f}%")
    
    # MFE by exit reason
    print(f"\n  MFE by Exit Reason:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        subset = [t["mfe_pct"] for t in trades if t["exit_reason"] == reason]
        if subset:
            print(f"    {reason:15s}: mean={np.mean(subset):+.2f}%  median={np.median(subset):+.2f}%  max={np.max(subset):+.2f}%")
    
    # What % of time-exits were profitable at some point?
    time_exit_trades = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_exit_trades:
        profitable_at_some_point = sum(1 for t in time_exit_trades if t["mfe_pct"] > 0)
        print(f"\n  Time-exit trades profitable at some point: {profitable_at_some_point}/{len(time_exit_trades)} ({profitable_at_some_point/len(time_exit_trades)*100:.1f}%)")
    
    # ========================================================================
    # SUMMARY
    # ========================================================================
    print("\n" + "=" * 70)
    print("RESEARCH SUMMARY")
    print("=" * 70)
    print(f"""
    Spring Reversal Strategy (Wyckoff Spring)
    
    Signal: New low + bullish close + close near high + high volume
    Parameters: lookback=20, vol_mult=1.5, close_pct=0.5
    Exits: stop=3.0%, target=5.0%, hold=24h
    
    Baseline (OKX):
      Sharpe: {sharpe:+.2f}
      Return: {total_sum:+.1f}%
      Max DD: {max_dd:+.1f}%
      Win Rate: {win_rate:.1f}%
      PF: {pf:.2f}
      Trades: {len(trades)}
    
    Walk-Forward: {profitable}/{len(wf_results)} splits profitable
      Mean OOS Sharpe: {mean_sharpe:+.2f}
    """)
    
    print("=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
