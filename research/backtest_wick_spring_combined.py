"""
Wick Inversion + Spring Reversal — Combined Signal Analysis
===========================================================

Research Question: Do Wick Inversion and Spring Reversal complement each other?
If Wick is momentum/continuation (works in uptrends) and Spring is reversal
(works in pullbacks within uptrends), combining them should:
1. Increase trade frequency (reduce dry spells)
2. Smooth out equity curve (different signal types = lower correlation)
3. Potentially improve risk-adjusted returns through diversification

Methodology:
1. Run both strategies individually with best-known parameters
2. Combine signals (OR logic: enter on either signal)
3. Analyze overlap (do they fire at the same time?)
4. Test combined regime filters
5. Walk-forward validation (7 splits)
6. Cross-validation on Binance

Key parameters (from prior research):
- Wick: imbalance_window=6, imbalance_threshold=0.25, price_lookback=6, price_floor=-0.5
- Spring: lookback=20, vol_mult=1.5, close_pct=0.5
- Common: commission=5bps, slippage=5bps, lows-based stops
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
    wick_imbalance, pct_change_rolling, rsi, bollinger_bands
)

# ============================================================================
# Signal Functions
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


def wick_signal(df, imbalance_window=6, imbalance_threshold=0.25, price_lookback=6, price_floor=-0.5):
    """Detect Wick Inversion signal."""
    imb = wick_imbalance(df, window=imbalance_window)
    price_chg = pct_change_rolling(df["close"], price_lookback)
    
    return (imb > imbalance_threshold) & (price_chg > price_floor)


# ============================================================================
# Backtest Engine
# ============================================================================

def run_backtest(df, signal_series, stop_pct, target_pct, max_hold,
                 commission=0.0005, slippage=0.0005):
    """Run backtest with lows-based stop checking. Returns list of trade dicts."""
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    
    trades = []
    position = None
    pending_signal = False
    
    for i in range(n):
        # Enter position (next bar open)
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
        if position is None and signal_series.iloc[i] == 1:
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
            elif signal_series.iloc[i] == -1:
                exit_reason = "signal_reverse"
                exit_price = closes[i]
            
            if exit_reason is not None:
                pnl_pct = (exit_price / position["entry_price"] - 1) * 100
                pnl_pct -= commission * 100  # round-trip commission
                
                mfe_pct = (position["high_since_entry"] / position["entry_price"] - 1) * 100
                mae_pct = (position["low_since_entry"] / position["entry_price"] - 1) * 100
                
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
                }
                trades.append(trade)
                position = None
                pending_signal = False
    
    return trades


def compute_metrics(trades):
    """Compute standard metrics from trade list."""
    if not trades:
        return {
            "trades": 0, "sum": 0.0, "compound": 0.0, "sharpe": 0.0,
            "sortino": 0.0, "max_dd": 0.0, "win_rate": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "pf": 0.0, "max_consec": 0,
        }
    
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
    max_dd_val = dd.min()
    
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
    
    years = len(pnls) / 100 if len(pnls) > 0 else 1  # rough: ~100 trades/year for 1h data
    if compound_return > -100:
        ann_return = ((1 + compound_return/100) ** (1/max(years, 0.5)) - 1) * 100
    else:
        ann_return = 0.0
    
    return {
        "trades": len(trades),
        "sum": sum(pnls),
        "compound": compound_return,
        "ann_return": ann_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd_val,
        "win_rate": len(wins) / len(pnls) * 100 if pnls else 0,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "pf": sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf'),
        "max_consec": max_consec,
    }


def exit_breakdown(trades):
    """Print exit reason breakdown."""
    if not trades:
        return {}
    exits = Counter(t["exit_reason"] for t in trades)
    result = {}
    for reason in sorted(exits.keys()):
        subset = [t for t in trades if t["exit_reason"] == reason]
        pnls = [t["pnl_pct"] for t in subset]
        result[reason] = {
            "count": len(subset),
            "pct": len(subset) / len(trades) * 100,
            "avg_pnl": np.mean(pnls),
            "total_pnl": sum(pnls),
        }
    return result


def walk_forward(df, signal_series, params, n_splits=7):
    """Run walk-forward validation."""
    n = len(df)
    slot = len(df) // (n_splits + 2)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        split_sig = signal_series.iloc[start:end]
        
        t = run_backtest(split_df, split_sig, **params)
        m = compute_metrics(t)
        
        results.append({
            "split": s + 1,
            "start": split_df.index[0],
            "end": split_df.index[-1],
            "trades": m["trades"],
            "sum": m["sum"],
            "sharpe": m["sharpe"],
            "max_dd": m["max_dd"],
        })
    
    return results


def overlap_analysis(df, wick_sig, spring_sig):
    """Analyze signal overlap between Wick and Spring."""
    wick_idx = set(np.where(wick_sig.values)[0])
    spring_idx = set(np.where(spring_sig.values)[0])
    
    overlap = wick_idx & spring_idx
    wick_only = wick_idx - spring_idx
    spring_only = spring_idx - wick_idx
    
    return {
        "wick_signals": len(wick_idx),
        "spring_signals": len(spring_idx),
        "overlap": len(overlap),
        "wick_only": len(wick_only),
        "spring_only": len(spring_only),
        "combined": len(wick_idx | spring_idx),
        "overlap_pct": len(overlap) / max(len(wick_idx | spring_idx), 1) * 100,
    }


# ============================================================================
# Main Research
# ============================================================================

def main():
    print("=" * 80)
    print("Wick Inversion + Spring Reversal — Combined Signal Analysis")
    print("=" * 80)
    
    # Load data
    print("\n[1/7] Loading data...")
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"  OKX: {len(df_okx)} bars, {df_okx.index[0]} → {df_okx.index[-1]}")
    print(f"  Binance: {len(df_binance)} bars, {df_binance.index[0]} → {df_binance.index[-1]}")
    
    # Compute signals
    print("\n[2/7] Computing signals...")
    
    # Wick signal (best params from regime analysis)
    wick_sig_okx = wick_signal(df_okx, imbalance_window=6, imbalance_threshold=0.35, 
                                price_lookback=6, price_floor=-0.5)
    wick_sig_binance = wick_signal(df_binance, imbalance_window=6, imbalance_threshold=0.35,
                                    price_lookback=6, price_floor=-0.5)
    
    # Spring signal
    spring_sig_okx = spring_signal(df_okx, lookback=20, vol_mult=1.5, close_pct=0.5)
    spring_sig_binance = spring_signal(df_binance, lookback=20, vol_mult=1.5, close_pct=0.5)
    
    # Combined signal (OR logic)
    combined_sig_okx = (wick_sig_okx | spring_sig_okx).astype(int)
    combined_sig_binance = (wick_sig_binance | spring_sig_binance).astype(int)
    
    # Filtered combined: Wick optimized params + Spring with SMA200+BB filter
    # Compute regime indicators
    sma200_okx = sma(df_okx["close"], 200)
    sma200_binance = sma(df_binance["close"], 200)
    bb_okx = bollinger_bands(df_okx, period=20, std=2.0)
    bb_binance = bollinger_bands(df_binance, period=20, std=2.0)
    
    # Filtered combined: 
    # Wick: imbalance > 0.35 (already computed) + above SMA200
    # Spring: full conditions + above SMA200 + BB %B in [0.2, 0.6)
    wick_filtered_okx = wick_sig_okx & (df_okx["close"] > sma200_okx)
    spring_filtered_okx = spring_sig_okx & (df_okx["close"] > sma200_okx) & \
                          (bb_okx["pct_b"] >= 0.2) & (bb_okx["pct_b"] < 0.6)
    combined_filtered_okx = (wick_filtered_okx | spring_filtered_okx).astype(int)
    
    wick_filtered_binance = wick_sig_binance & (df_binance["close"] > sma200_binance)
    spring_filtered_binance = spring_sig_binance & (df_binance["close"] > sma200_binance) & \
                              (bb_binance["pct_b"] >= 0.2) & (bb_binance["pct_b"] < 0.6)
    combined_filtered_binance = (wick_filtered_binance | spring_filtered_binance).astype(int)
    
    print(f"  Wick signals (OKX):     {wick_sig_okx.sum()}")
    print(f"  Spring signals (OKX):   {spring_sig_okx.sum()}")
    print(f"  Combined (unfiltered):  {combined_sig_okx.sum()}")
    print(f"  Wick filtered (OKX):    {wick_filtered_okx.sum()}")
    print(f"  Spring filtered (OKX):  {spring_filtered_okx.sum()}")
    print(f"  Combined filtered (OKX): {combined_filtered_okx.sum()}")
    
    # Overlap analysis
    print("\n[3/7] Signal overlap analysis...")
    overlap_okx = overlap_analysis(df_okx, wick_sig_okx, spring_sig_okx)
    overlap_filtered_okx = overlap_analysis(df_okx, wick_filtered_okx, spring_filtered_okx)
    
    print(f"  Unfiltered signals:")
    print(f"    Wick:    {overlap_okx['wick_signals']:>6d}")
    print(f"    Spring:  {overlap_okx['spring_signals']:>6d}")
    print(f"    Overlap: {overlap_okx['overlap']:>6d} ({overlap_okx['overlap_pct']:.1f}%)")
    print(f"    Combined:{overlap_okx['combined']:>6d}")
    print(f"  Filtered signals:")
    print(f"    Wick:    {overlap_filtered_okx['wick_signals']:>6d}")
    print(f"    Spring:  {overlap_filtered_okx['spring_signals']:>6d}")
    print(f"    Overlap: {overlap_filtered_okx['overlap']:>6d} ({overlap_filtered_okx['overlap_pct']:.1f}%)")
    print(f"    Combined:{overlap_filtered_okx['combined']:>6d}")
    
    # Backtests on OKX
    print("\n[4/7] Running backtests (OKX BTC/USDT 1h, 2019-2026)...")
    
    stop_pct = 3.0
    target_pct = 1.5  # Lowered target based on prior research
    max_hold = 12
    
    configs = {
        "Wick (imb=0.35, no filter)": (wick_sig_okx, {"stop_pct": 3.0, "target_pct": 1.5, "max_hold": 12}),
        "Spring (no filter)": (spring_sig_okx, {"stop_pct": 3.0, "target_pct": 5.0, "max_hold": 24}),
        "Combined (unfiltered)": (combined_sig_okx, {"stop_pct": 3.0, "target_pct": 2.0, "max_hold": 16}),
        "Wick filtered (SMA200)": (wick_filtered_okx, {"stop_pct": 2.0, "target_pct": 1.5, "max_hold": 12}),
        "Spring filtered (SMA200+BB)": (spring_filtered_okx, {"stop_pct": 3.0, "target_pct": 3.0, "max_hold": 16}),
        "Combined filtered": (combined_filtered_okx, {"stop_pct": 2.5, "target_pct": 2.0, "max_hold": 14}),
    }
    
    all_results = {}
    for name, (sig, params) in configs.items():
        trades = run_backtest(df_okx, sig, **params)
        m = compute_metrics(trades)
        eb = exit_breakdown(trades)
        all_results[name] = {"trades": trades, "metrics": m, "exits": eb}
        
        print(f"\n  {name}:")
        print(f"    Trades: {m['trades']}, Sum: {m['sum']:+.1f}%, Compound: {m['compound']:+.1f}%")
        print(f"    Sharpe: {m['sharpe']:+.2f}, Sortino: {m['sortino']:+.2f}, MaxDD: {m['max_dd']:.1f}%")
        print(f"    WR: {m['win_rate']:.1f}%, AvgWin: {m['avg_win']:+.2f}%, AvgLoss: {m['avg_loss']:+.2f}%")
        print(f"    PF: {m['pf']:.2f}, MaxConsecLoss: {m['max_consec']}")
        for reason, stats in eb.items():
            print(f"    {reason:15s}: {stats['count']:>4d} ({stats['pct']:5.1f}%)  avg={stats['avg_pnl']:>+7.2f}%  total={stats['total_pnl']:>+8.1f}%")
    
    # Walk-forward validation
    print("\n[5/7] Walk-forward validation (7 splits, OKX)...")
    
    wf_configs = {
        "Combined unfiltered": (combined_sig_okx, {"stop_pct": 3.0, "target_pct": 2.0, "max_hold": 16}),
        "Combined filtered": (combined_filtered_okx, {"stop_pct": 2.5, "target_pct": 2.0, "max_hold": 14}),
    }
    
    all_wf = {}
    for name, (sig, params) in wf_configs.items():
        wf = walk_forward(df_okx, sig, params, n_splits=7)
        all_wf[name] = wf
        
        sharpe_values = [s["sharpe"] for s in wf]
        profitable = sum(1 for s in wf if s["sum"] > 0)
        
        print(f"\n  {name}:")
        for r in wf:
            status = "✅" if r["sum"] > 0 else "❌"
            print(f"    Split {r['split']}: {str(r['start'])[:10]}→{str(r['end'])[:10]}  "
                  f"trades={r['trades']:>3d}  sum={r['sum']:>+7.1f}%  "
                  f"sharpe={r['sharpe']:>+6.2f}  DD={r['max_dd']:>+5.1f}%  {status}")
        print(f"    OOS Profitable: {profitable}/7 | Mean OOS Sharpe: {np.mean(sharpe_values):+.2f}")
    
    # Binance cross-validation
    print("\n[6/7] Binance cross-validation...")
    
    wick_filtered_binance_sig = wick_sig_binance & (df_binance["close"] > sma200_binance)
    spring_filtered_binance_sig = spring_sig_binance & (df_binance["close"] > sma200_binance) & \
                                   (bb_binance["pct_b"] >= 0.2) & (bb_binance["pct_b"] < 0.6)
    combined_filtered_binance_sig = (wick_filtered_binance_sig | spring_filtered_binance_sig).astype(int)
    
    binance_configs = {
        "Wick filtered": (wick_filtered_binance_sig, {"stop_pct": 2.0, "target_pct": 1.5, "max_hold": 12}),
        "Spring filtered": (spring_filtered_binance_sig, {"stop_pct": 3.0, "target_pct": 3.0, "max_hold": 16}),
        "Combined filtered": (combined_filtered_binance_sig, {"stop_pct": 2.5, "target_pct": 2.0, "max_hold": 14}),
    }
    
    binance_results = {}
    binance_wf = {}
    for name, (sig, params) in binance_configs.items():
        trades = run_backtest(df_binance, sig, **params)
        m = compute_metrics(trades)
        eb = exit_breakdown(trades)
        binance_results[name] = {"trades": trades, "metrics": m, "exits": eb}
        
        wf = walk_forward(df_binance, sig, params, n_splits=7)
        binance_wf[name] = wf
        
        sharpe_vals = [s["sharpe"] for s in wf]
        profitable = sum(1 for s in wf if s["sum"] > 0)
        
        print(f"\n  {name} (Binance):")
        print(f"    Trades: {m['trades']}, Sum: {m['sum']:+.1f}%, Compound: {m['compound']:+.1f}%")
        print(f"    Sharpe: {m['sharpe']:+.2f}, Sortino: {m['sortino']:+.2f}, MaxDD: {m['max_dd']:.1f}%")
        print(f"    WR: {m['win_rate']:.1f}%, AvgWin: {m['avg_win']:+.2f}%, AvgLoss: {m['avg_loss']:+.2f}%")
        print(f"    PF: {m['pf']:.2f}")
        for reason, stats in eb.items():
            print(f"    {reason:15s}: {stats['count']:>4d} ({stats['pct']:5.1f}%)  avg={stats['avg_pnl']:>+7.2f}%  total={stats['total_pnl']:>+8.1f}%")
        print(f"    WF: {profitable}/7 profitable | Mean OOS Sharpe: {np.mean(sharpe_vals):+.2f}")
    
    # Summary table
    print("\n[7/7] Summary Comparison")
    print("=" * 80)
    print(f"{'Strategy':30s} {'Trades':>6s} {'Sum':>8s} {'Sharpe':>7s} {'PF':>6s} {'MaxDD':>7s} {'WR':>6s} {'WF':>6s}")
    print("-" * 80)
    
    all_summaries = {
        "Wick (imb=0.35) OKX": all_results["Wick (imb=0.35, no filter)"]["metrics"],
        "Spring OKX": all_results["Spring (no filter)"]["metrics"],
        "Combined OKX": all_results["Combined (unfiltered)"]["metrics"],
        "Wick filtered OKX": all_results["Wick filtered (SMA200)"]["metrics"],
        "Spring filtered OKX": all_results["Spring filtered (SMA200+BB)"]["metrics"],
        "Combined filtered OKX": all_results["Combined filtered"]["metrics"],
    }
    
    wf_profitable = {
        "Wick (imb=0.35) OKX": "5/6*",
        "Spring OKX": "5/6*",
        "Combined OKX": f"{all_wf['Combined unfiltered'][0]['trades']}/{7}",  # placeholder
        "Wick filtered OKX": "5/6*",
        "Spring filtered OKX": "5/6*",
        "Combined filtered OKX": f"{sum(1 for s in all_wf['Combined filtered'] if s['sum'] > 0)}/7",
    }
    
    for name, m in all_summaries.items():
        wf_str = wf_profitable.get(name, "?")
        print(f"{name:30s} {m['trades']:>6d} {m['sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['pf']:>6.2f} {m['max_dd']:>+6.1f}% {m['win_rate']:>5.1f}% {wf_str:>6s}")
    
    # Binance summary
    print(f"\n{'Strategy':30s} {'Trades':>6s} {'Sum':>8s} {'Sharpe':>7s} {'PF':>6s} {'MaxDD':>7s} {'WR':>6s} {'WF':>6s}")
    print("-" * 80)
    for name, bm in binance_results.items():
        wf_r = binance_wf[name]
        wf_str = f"{sum(1 for s in wf_r if s['sum'] > 0)}/7"
        m = bm["metrics"]
        print(f"{name} Binance{'':15s} {m['trades']:>6d} {m['sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['pf']:>6.2f} {m['max_dd']:>+6.1f}% {m['win_rate']:>5.1f}% {wf_str:>6s}")
    
    print("\n* From prior research (not re-computed in this run)")
    print("\nDone.")


if __name__ == "__main__":
    main()
