"""
Spring Reversal — Consecutive Loss Cooldown Mechanism
=====================================================

The Spring Reversal regime analysis (research_regime_analysis_v1.md) found that
after consecutive losses, win rate degrades:
  - After 1 loss: 44.4% WR, avg -0.11%
  - After 2 losses: 43.5% WR, avg -0.30%
  - After 3 losses: 38.5% WR, avg -0.56%
  - After 5 losses: 25.0% WR, avg -1.06%

Hypothesis: A cooldown mechanism that pauses trading after N consecutive losses
will improve risk-adjusted returns by avoiding losing streaks.

Tested:
1. Baseline (no cooldown): SMA200 + BB %B 0.2-0.6, s3.0/t3.0/h16
2. Cooldown after 1 loss
3. Cooldown after 2 losses
4. Cooldown after 3 losses
5. Grid search: cooldown N × bars to skip
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
# Custom backtest with cooldown mechanism
# ============================================================================

def cooldown_backtest(df, signals, regime_data, stop_pct=3.0, target_pct=3.0,
                      max_hold=16, commission=0.0005, slippage=0.0005,
                      cooldown_losses=0, cooldown_bars=1):
    """
    Run backtest with consecutive-loss cooldown mechanism.
    
    Parameters:
        cooldown_losses: int — number of consecutive losses before triggering cooldown.
                         0 means no cooldown (baseline).
        cooldown_bars: int — number of bars to skip after cooldown triggers.
    """
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    
    trades = []
    position = None
    pending_signal = False
    consecutive_losses = 0
    cooldown_until = -1  # bar index until which we skip signals
    
    for i in range(n):
        # Skip signals during cooldown
        if i < cooldown_until:
            pending_signal = False
        
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
        
        # Check signal for next bar entry (only if not in cooldown)
        if position is None and signals.iloc[i] == 1 and i >= cooldown_until:
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
                
                # Track consecutive losses for cooldown
                if pnl_pct <= 0:
                    consecutive_losses += 1
                    if cooldown_losses > 0 and consecutive_losses >= cooldown_losses:
                        cooldown_until = i + cooldown_bars
                        consecutive_losses = 0  # reset after triggering cooldown
                else:
                    consecutive_losses = 0
                
                position = None
                pending_signal = False
    
    return trades


# ============================================================================
# Walk-Forward Validation
# ============================================================================

def walk_forward_cooldown(df, signal_series, regime_data, n_splits=7, **kwargs):
    """Run walk-forward validation with cooldown."""
    n = len(df)
    slot = len(df) // (n_splits + 2)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        split_sig = signal_series.iloc[start:end]
        split_regime = {k: v[start:end] if isinstance(v, (np.ndarray, pd.Series)) else v 
                       for k, v in regime_data.items()}
        
        trades = cooldown_backtest(split_df, split_sig, split_regime, **kwargs)
        
        pnls = [t["pnl_pct"] for t in trades]
        total_sum = sum(pnls)
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
        
        # Get period
        period_start = split_df.index[0]
        period_end = split_df.index[-1]
        if hasattr(period_start, 'strftime'):
            period_str = f"{period_start.strftime('%Y-%m')}→{period_end.strftime('%Y-%m')}"
        else:
            period_str = f"split_{s}"
        
        results.append({
            "split": s + 1,
            "period": period_str,
            "trades": len(trades),
            "sum": total_sum,
            "sharpe": sharpe,
            "profitable": total_sum > 0,
        })
    
    return results


# ============================================================================
# Print Functions
# ============================================================================

def print_trade_summary(trades, label=""):
    """Print comprehensive trade summary."""
    if not trades:
        print(f"\n{label}: NO TRADES")
        return
    
    pnls = [t["pnl_pct"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    # Compound return
    compound = 1.0
    for p in pnls:
        compound *= (1 + p / 100)
    compound_pct = (compound - 1) * 100
    
    # Linear sum
    linear_sum = sum(pnls)
    
    # Sharpe
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
    
    # Sortino
    downside = [p for p in pnls if p < 0]
    sortino = np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)) if downside and np.std(downside) > 0 else 0
    
    # Max drawdown (from linear sum)
    cumulative = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative - running_max
    max_dd = np.min(drawdowns) if len(drawdowns) > 0 else 0
    
    # Win rate
    wr = len(wins) / len(pnls) * 100 if pnls else 0
    
    # Avg win/loss
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    
    # Profit factor
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
    
    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for p in pnls:
        if p <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0
    
    # Exit breakdown
    exit_counts = Counter(t["exit_reason"] for t in trades)
    
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Trades:       {len(trades)}")
    print(f"  Compound Return:    {compound_pct:+.1f}%")
    print(f"  Linear Sum:         {linear_sum:+.1f}%")
    print(f"  Sharpe Ratio:       {sharpe:+.2f}")
    print(f"  Sortino Ratio:      {sortino:+.2f}")
    print(f"  Max Drawdown:       {max_dd:+.1f}%")
    print(f"  Win Rate:           {wr:.1f}%")
    print(f"  Avg Win:            {avg_win:+.2f}%")
    print(f"  Avg Loss:           {avg_loss:+.2f}%")
    print(f"  Profit Factor:      {pf:.2f}")
    print(f"  Max Consec Losses:  {max_consec}")
    print()
    print(f"  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        count = exit_counts.get(reason, 0)
        if count > 0:
            subset = [t for t in trades if t["exit_reason"] == reason]
            avg = np.mean([t["pnl_pct"] for t in subset])
            total = sum([t["pnl_pct"] for t in subset])
            pct = count / len(trades) * 100
            print(f"    {reason:15s} {count:>4d} ({pct:5.1f}%)  avg={avg:+.2f}%  total={total:+.1f}%")
    
    # MFE analysis
    mfes = [t["mfe_pct"] for t in trades]
    print(f"\n  MFE: mean={np.mean(mfes):+.2f}%, median={np.median(mfes):+.2f}%, max={np.max(mfes):+.2f}%")
    
    # Time-exit MFE
    time_trades = [t for t in trades if t["exit_reason"] == "time_exit"]
    if time_trades:
        profitable_mfe = sum(1 for t in time_trades if t["mfe_pct"] > 0)
        print(f"  Time-exits profitable at some point: {profitable_mfe}/{len(time_trades)} ({profitable_mfe/len(time_trades)*100:.1f}%)")
    
    return {
        "trades": len(trades),
        "compound": compound_pct,
        "linear_sum": linear_sum,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": wr,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": pf,
        "max_consec_losses": max_consec,
        "exit_breakdown": dict(exit_counts),
    }


def print_wf_results(results, label=""):
    """Print walk-forward results."""
    print(f"\n--- Walk-Forward: {label} ---")
    print(f"{'Split':>6s} {'Period':22s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>8s} {'Status':>7s}")
    print("-" * 65)
    
    profitable = 0
    sharpes = []
    for r in results:
        status = "✅" if r["profitable"] else "❌"
        if r["profitable"]:
            profitable += 1
        sharpes.append(r["sharpe"])
        print(f"{r['split']:>6d} {r['period']:22s} {r['trades']:>7d} {r['sum']:>+7.1f}% {r['sharpe']:>+8.2f} {status:>7s}")
    
    mean_sharpe = np.mean(sharpes) if sharpes else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"\n  OOS Profitable: {profitable}/{len(results)} splits")
    print(f"  Mean OOS Sharpe: {mean_sharpe:+.2f}")
    print(f"  Total OOS Sum: {total_sum:+.1f}%")


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print("  Spring Reversal — Consecutive Loss Cooldown Research")
    print("=" * 60)
    
    # Load data
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nLoaded OKX BTC/USDT 1h: {len(df)} bars, {df.index[0]} → {df.index[-1]}")
    
    # Compute signals
    print("\nComputing signals...")
    spring_sig = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
    
    # Compute regime data
    print("Computing regime indicators...")
    closes = df["close"]
    highs = df["high"]
    lows = df["low"]
    
    sma200 = sma(closes, 200)
    bb = bollinger_bands(df, period=20, std=2.0)
    bb_pct_b = bb["pct_b"]
    
    regime_data = {
        "sma200": sma200,
        "bb_pct_b": bb_pct_b,
    }
    
    # Create filtered signal: SMA200 + BB %B 0.2-0.6
    filtered_signal = spring_sig & (closes > sma200) & (bb_pct_b >= 0.2) & (bb_pct_b < 0.6)
    filtered_signal = filtered_signal.astype(int)
    
    # Also create unfiltered signal for comparison
    unfiltered_signal = spring_sig.astype(int)
    
    print(f"  Raw Spring signals: {spring_sig.sum()}")
    print(f"  Filtered signals (SMA200 + BB 0.2-0.6): {filtered_signal.sum()}")
    
    # ========================================================================
    # 1. BASELINE: No Cooldown (s3.0/t3.0/h16) — FILTERED
    # ========================================================================
    print("\n" + "=" * 60)
    print("  1. BASELINE: Filtered Spring, No Cooldown (s3.0/t3.0/h16)")
    print("=" * 60)
    
    baseline_trades = cooldown_backtest(
        df, filtered_signal, regime_data,
        stop_pct=3.0, target_pct=3.0, max_hold=16,
        cooldown_losses=0, cooldown_bars=0
    )
    baseline_metrics = print_trade_summary(baseline_trades, "Baseline Filtered (no cooldown)")
    
    # Walk-forward
    baseline_wf = walk_forward_cooldown(
        df, filtered_signal, regime_data, n_splits=7,
        stop_pct=3.0, target_pct=3.0, max_hold=16,
        cooldown_losses=0, cooldown_bars=0
    )
    print_wf_results(baseline_wf, "Baseline Filtered (no cooldown)")
    
    # ========================================================================
    # 1b. BASELINE: UNFILTERED Spring (s3.0/t5.0/h24)
    # ========================================================================
    print("\n" + "=" * 60)
    print("  1b. BASELINE: UNFILTERED Spring, No Cooldown (s3.0/t5.0/h24)")
    print("=" * 60)
    
    baseline_unfiltered_trades = cooldown_backtest(
        df, unfiltered_signal, regime_data,
        stop_pct=3.0, target_pct=5.0, max_hold=24,
        cooldown_losses=0, cooldown_bars=0
    )
    baseline_unfiltered_metrics = print_trade_summary(baseline_unfiltered_trades, "Baseline Unfiltered (no cooldown)")
    
    baseline_unfiltered_wf = walk_forward_cooldown(
        df, unfiltered_signal, regime_data, n_splits=7,
        stop_pct=3.0, target_pct=5.0, max_hold=24,
        cooldown_losses=0, cooldown_bars=0
    )
    print_wf_results(baseline_unfiltered_wf, "Baseline Unfiltered (no cooldown)")
    
    # ========================================================================
    # 2. Cooldown after N consecutive losses — sweep (FILTERED)
    # ========================================================================
    print("\n" + "=" * 60)
    print("  2. COOLDOWN SWEEP: Filtered Spring (s3.0/t3.0/h16)")
    print("=" * 60)
    
    cooldown_configs = [
        (1, 1), (1, 2), (1, 3),
        (2, 1), (2, 2), (2, 3),
        (3, 1), (3, 2), (3, 3),
        (4, 1), (4, 2), (4, 3),
    ]
    
    print(f"\n{'Cooldown':>12s} {'Skip':>6s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>8s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s} {'WF':>5s}")
    print("-" * 75)
    
    all_results = []
    for cd_losses, cd_bars in cooldown_configs:
        trades = cooldown_backtest(
            df, filtered_signal, regime_data,
            stop_pct=3.0, target_pct=3.0, max_hold=16,
            cooldown_losses=cd_losses, cooldown_bars=cd_bars
        )
        
        if not trades:
            continue
        
        pnls = [t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        linear_sum = sum(pnls)
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
        wr = len(wins) / len(pnls) * 100 if pnls else 0
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
        
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        max_dd = np.min(cumulative - running_max)
        
        # Walk-forward
        wf = walk_forward_cooldown(
            df, filtered_signal, regime_data, n_splits=7,
            stop_pct=3.0, target_pct=3.0, max_hold=16,
            cooldown_losses=cd_losses, cooldown_bars=cd_bars
        )
        wf_profitable = sum(1 for r in wf if r["profitable"])
        wf_mean_sharpe = np.mean([r["sharpe"] for r in wf])
        
        config_label = f"cd={cd_losses},skip={cd_bars}"
        print(f"{config_label:>12s} {cd_bars:>6d} {len(trades):>7d} {linear_sum:>+7.1f}% {sharpe:>+8.2f} {wr:>5.1f}% {pf:>5.2f} {max_dd:>+6.1f}% {wf_profitable}/{len(wf)}")
        
        all_results.append({
            "cd_losses": cd_losses,
            "cd_bars": cd_bars,
            "trades": len(trades),
            "sum": linear_sum,
            "sharpe": sharpe,
            "wr": wr,
            "pf": pf,
            "max_dd": max_dd,
            "wf_profitable": wf_profitable,
            "wf_total": len(wf),
            "wf_mean_sharpe": wf_mean_sharpe,
            "trades_data": trades,
            "wf_data": wf,
        })
    
    # ========================================================================
    # 2b. Cooldown sweep — UNFILTERED
    # ========================================================================
    print("\n" + "=" * 60)
    print("  2b. COOLDOWN SWEEP: Unfiltered Spring (s3.0/t5.0/h24)")
    print("=" * 60)
    
    print(f"\n{'Cooldown':>12s} {'Skip':>6s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>8s} {'WR':>6s} {'PF':>6s} {'MaxDD':>7s} {'WF':>5s}")
    print("-" * 75)
    
    all_unfiltered_results = []
    for cd_losses, cd_bars in cooldown_configs:
        trades = cooldown_backtest(
            df, unfiltered_signal, regime_data,
            stop_pct=3.0, target_pct=5.0, max_hold=24,
            cooldown_losses=cd_losses, cooldown_bars=cd_bars
        )
        
        if not trades:
            continue
        
        pnls = [t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        
        linear_sum = sum(pnls)
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)) if len(pnls) > 1 and np.std(pnls) > 0 else 0
        wr = len(wins) / len(pnls) * 100 if pnls else 0
        pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
        
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        max_dd = np.min(cumulative - running_max)
        
        # Walk-forward
        wf = walk_forward_cooldown(
            df, unfiltered_signal, regime_data, n_splits=7,
            stop_pct=3.0, target_pct=5.0, max_hold=24,
            cooldown_losses=cd_losses, cooldown_bars=cd_bars
        )
        wf_profitable = sum(1 for r in wf if r["profitable"])
        wf_mean_sharpe = np.mean([r["sharpe"] for r in wf])
        
        config_label = f"cd={cd_losses},skip={cd_bars}"
        print(f"{config_label:>12s} {cd_bars:>6d} {len(trades):>7d} {linear_sum:>+7.1f}% {sharpe:>+8.2f} {wr:>5.1f}% {pf:>5.2f} {max_dd:>+6.1f}% {wf_profitable}/{len(wf)}")
        
        all_unfiltered_results.append({
            "cd_losses": cd_losses,
            "cd_bars": cd_bars,
            "trades": len(trades),
            "sum": linear_sum,
            "sharpe": sharpe,
            "wr": wr,
            "pf": pf,
            "max_dd": max_dd,
            "wf_profitable": wf_profitable,
            "wf_total": len(wf),
            "wf_mean_sharpe": wf_mean_sharpe,
            "trades_data": trades,
            "wf_data": wf,
        })
    
    # ========================================================================
    # 3. Best cooldown — detailed analysis
    # ========================================================================
    print("\n" + "=" * 60)
    print("  3. BEST COOLDOWN — Filtered Spring")
    print("=" * 60)
    
    # Find best by WF mean Sharpe
    best = max(all_results, key=lambda x: x["wf_mean_sharpe"])
    print(f"\nBest config: cooldown after {best['cd_losses']} losses, skip {best['cd_bars']} bars")
    print(f"  WF mean Sharpe: {best['wf_mean_sharpe']:+.2f}, {best['wf_profitable']}/{best['wf_total']} profitable")
    
    print_trade_summary(best["trades_data"], f"Best Cooldown Filtered (cd={best['cd_losses']}, skip={best['cd_bars']})")
    print_wf_results(best["wf_data"], f"Best Cooldown Filtered (cd={best['cd_losses']}, skip={best['cd_bars']})")
    
    # ========================================================================
    # 3b. Best cooldown — UNFILTERED
    # ========================================================================
    print("\n" + "=" * 60)
    print("  3b. BEST COOLDOWN — Unfiltered Spring")
    print("=" * 60)
    
    best_unfiltered = max(all_unfiltered_results, key=lambda x: x["wf_mean_sharpe"])
    print(f"\nBest config: cooldown after {best_unfiltered['cd_losses']} losses, skip {best_unfiltered['cd_bars']} bars")
    print(f"  WF mean Sharpe: {best_unfiltered['wf_mean_sharpe']:+.2f}, {best_unfiltered['wf_profitable']}/{best_unfiltered['wf_total']} profitable")
    
    print_trade_summary(best_unfiltered["trades_data"], f"Best Cooldown Unfiltered (cd={best_unfiltered['cd_losses']}, skip={best_unfiltered['cd_bars']})")
    print_wf_results(best_unfiltered["wf_data"], f"Best Cooldown Unfiltered (cd={best_unfiltered['cd_losses']}, skip={best_unfiltered['cd_bars']})")
    
    # ========================================================================
    # 4. Comparison tables
    # ========================================================================
    print("\n" + "=" * 60)
    print("  4. COMPARISON: Filtered Spring — Baseline vs Best Cooldown")
    print("=" * 60)
    
    print(f"\n{'Metric':20s} {'Baseline':>12s} {'Best Cooldown':>15s} {'Delta':>10s}")
    print("-" * 60)
    
    comparisons = [
        ("Sharpe", baseline_metrics["sharpe"], best["sharpe"]),
        ("Linear Sum", baseline_metrics["linear_sum"], best["sum"]),
        ("Compound", baseline_metrics["compound"], 0),
        ("Max DD", baseline_metrics["max_dd"], best["max_dd"]),
        ("Win Rate", baseline_metrics["win_rate"], best["wr"]),
        ("Profit Factor", baseline_metrics["profit_factor"], best["pf"]),
        ("Trades", baseline_metrics["trades"], best["trades"]),
        ("Max Consec Loss", baseline_metrics["max_consec_losses"], 0),
        ("WF Mean Sharpe", np.mean([r["sharpe"] for r in baseline_wf]), best["wf_mean_sharpe"]),
        ("WF Profitable", sum(1 for r in baseline_wf if r["profitable"]), best["wf_profitable"]),
    ]
    
    best_compound = 1.0
    for t in best["trades_data"]:
        best_compound *= (1 + t["pnl_pct"] / 100)
    best_compound = (best_compound - 1) * 100
    
    best_max_consec = 0
    curr = 0
    for t in best["trades_data"]:
        if t["pnl_pct"] <= 0:
            curr += 1
            best_max_consec = max(best_max_consec, curr)
        else:
            curr = 0
    
    for name, base_val, best_val in comparisons:
        if name == "Compound":
            best_val = best_compound
        elif name == "Max Consec Loss":
            best_val = best_max_consec
        
        if isinstance(base_val, float):
            delta = best_val - base_val
            if name in ("Sharpe", "WF Mean Sharpe"):
                print(f"{name:20s} {base_val:>+12.2f} {best_val:>+15.2f} {delta:>+10.2f}")
            elif name in ("Max DD",):
                print(f"{name:20s} {base_val:>+11.1f}% {best_val:>+14.1f}% {delta:>+9.1f}%")
            elif name in ("Linear Sum", "Compound"):
                print(f"{name:20s} {base_val:>+11.1f}% {best_val:>+14.1f}% {delta:>+9.1f}%")
            elif name in ("Win Rate",):
                print(f"{name:20s} {base_val:>11.1f}% {best_val:>14.1f}% {delta:>+9.1f}%")
            else:
                print(f"{name:20s} {base_val:>12.2f} {best_val:>15.2f} {delta:>+10.2f}")
        elif isinstance(base_val, int):
            delta = best_val - base_val
            print(f"{name:20s} {base_val:>12d} {best_val:>15d} {delta:>+10d}")
    
    # ========================================================================
    # 4b. Unfiltered comparison
    # ========================================================================
    print("\n" + "=" * 60)
    print("  4b. COMPARISON: Unfiltered Spring — Baseline vs Best Cooldown")
    print("=" * 60)
    
    print(f"\n{'Metric':20s} {'Baseline':>12s} {'Best Cooldown':>15s} {'Delta':>10s}")
    print("-" * 60)
    
    comparisons_uf = [
        ("Sharpe", baseline_unfiltered_metrics["sharpe"], best_unfiltered["sharpe"]),
        ("Linear Sum", baseline_unfiltered_metrics["linear_sum"], best_unfiltered["sum"]),
        ("Compound", baseline_unfiltered_metrics["compound"], 0),
        ("Max DD", baseline_unfiltered_metrics["max_dd"], best_unfiltered["max_dd"]),
        ("Win Rate", baseline_unfiltered_metrics["win_rate"], best_unfiltered["wr"]),
        ("Profit Factor", baseline_unfiltered_metrics["profit_factor"], best_unfiltered["pf"]),
        ("Trades", baseline_unfiltered_metrics["trades"], best_unfiltered["trades"]),
        ("Max Consec Loss", baseline_unfiltered_metrics["max_consec_losses"], 0),
        ("WF Mean Sharpe", np.mean([r["sharpe"] for r in baseline_unfiltered_wf]), best_unfiltered["wf_mean_sharpe"]),
        ("WF Profitable", sum(1 for r in baseline_unfiltered_wf if r["profitable"]), best_unfiltered["wf_profitable"]),
    ]
    
    best_uf_compound = 1.0
    for t in best_unfiltered["trades_data"]:
        best_uf_compound *= (1 + t["pnl_pct"] / 100)
    best_uf_compound = (best_uf_compound - 1) * 100
    
    best_uf_max_consec = 0
    curr = 0
    for t in best_unfiltered["trades_data"]:
        if t["pnl_pct"] <= 0:
            curr += 1
            best_uf_max_consec = max(best_uf_max_consec, curr)
        else:
            curr = 0
    
    for name, base_val, best_val in comparisons_uf:
        if name == "Compound":
            best_val = best_uf_compound
        elif name == "Max Consec Loss":
            best_val = best_uf_max_consec
        
        if isinstance(base_val, float):
            delta = best_val - base_val
            if name in ("Sharpe", "WF Mean Sharpe"):
                print(f"{name:20s} {base_val:>+12.2f} {best_val:>+15.2f} {delta:>+10.2f}")
            elif name in ("Max DD",):
                print(f"{name:20s} {base_val:>+11.1f}% {best_val:>+14.1f}% {delta:>+9.1f}%")
            elif name in ("Linear Sum", "Compound"):
                print(f"{name:20s} {base_val:>+11.1f}% {best_val:>+14.1f}% {delta:>+9.1f}%")
            elif name in ("Win Rate",):
                print(f"{name:20s} {base_val:>11.1f}% {best_val:>14.1f}% {delta:>+9.1f}%")
            else:
                print(f"{name:20s} {base_val:>12.2f} {best_val:>15.2f} {delta:>+10.2f}")
        elif isinstance(base_val, int):
            delta = best_val - base_val
            print(f"{name:20s} {base_val:>12d} {best_val:>15d} {delta:>+10d}")
    
    # ========================================================================
    # 5. Cooldown impact on trade quality
    # ========================================================================
    print("\n" + "=" * 60)
    print("  5. COOLDOWN IMPACT: Which Trades Were Skipped?")
    print("=" * 60)
    
    # Identify trades that would have been skipped
    baseline_trade_indices = set(t["entry_idx"] for t in baseline_trades)
    best_trade_indices = set(t["entry_idx"] for t in best["trades_data"])
    skipped_indices = baseline_trade_indices - best_trade_indices
    
    if skipped_indices:
        skipped_trades = [t for t in baseline_trades if t["entry_idx"] in skipped_indices]
        skipped_pnls = [t["pnl_pct"] for t in skipped_trades]
        skipped_wins = sum(1 for p in skipped_pnls if p > 0)
        
        print(f"  Trades skipped by cooldown: {len(skipped_trades)}")
        print(f"  Skipped PnL sum: {sum(skipped_pnls):+.1f}%")
        print(f"  Skipped win rate: {skipped_wins}/{len(skipped_trades)} ({skipped_wins/len(skipped_trades)*100:.1f}%)")
        print(f"  Skipped avg PnL: {np.mean(skipped_pnls):+.2f}%")
        
        # Exit reasons of skipped trades
        skipped_exits = Counter(t["exit_reason"] for t in skipped_trades)
        print(f"  Skipped exit breakdown:")
        for reason in ["take_profit", "stop_loss", "time_exit"]:
            count = skipped_exits.get(reason, 0)
            if count > 0:
                subset = [t for t in skipped_trades if t["exit_reason"] == reason]
                avg = np.mean([t["pnl_pct"] for t in subset])
                print(f"    {reason}: {count} trades, avg={avg:+.2f}%")
    else:
        print("  No trades were skipped (cooldown never triggered)")
    
    print("\n" + "=" * 60)
    print("  Research complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
