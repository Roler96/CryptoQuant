"""
Spring Reversal — BB %B Filter WITHOUT SMA200: Expanding Trade Count
===========================================================================

Hypothesis: The SMA200 filter eliminates 71% of trades, but the regime analysis
showed that %B [0.12, 0.65) below SMA200 is also profitable post-hoc (135 trades,
Sharpe +1.65). With optimized exits (s3.0/t2.75/h32), dropping SMA200 could 
significantly increase trade count while maintaining deployable Sharpe.

Tests:
1. BB [0.12, 0.65) with SMA200 (baseline, v1.2.0)
2. BB [0.12, 0.65) WITHOUT SMA200 (experiment)
3. BB [0.10, 0.70) WITHOUT SMA200 (aggressive expansion)
4. Walk-forward validation on all
5. Binance cross-validation
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, bollinger_bands, spring_reversal_signal,
)

# ============================================================================
# Custom backtest with lows-based stops
# ============================================================================

def backtest_spring(df, signal, stop_pct=3.0, target_pct=2.75, max_hold=32,
                    commission=0.0005, slippage=0.0005):
    """
    Vectorized backtest for Spring strategy.
    Entry: next bar open after signal.
    Stops: checked against bar low (not close).
    Exit priority: stop > target > time > signal_reverse.
    """
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    sig = signal.values if hasattr(signal, 'values') else signal
    
    n = len(df)
    trades = []
    in_position = False
    entry_idx = 0
    entry_price = 0.0
    high_since = 0.0
    low_since = 0.0
    
    for i in range(1, n):
        # ENTRY FIRST: signal at bar i-1 triggers entry at bar i open
        # (no look-ahead: sig[i-1] only uses data up to bar i-1)
        if not in_position and sig[i-1] == 1:
            in_position = True
            entry_idx = i
            entry_price = opens[i] * (1 + slippage)
            high_since = highs[i]
            low_since = lows[i]
        
        # THEN CHECK EXITS (including on entry bar)
        if in_position:
            hold_bars = i - entry_idx
            exit_reason = None
            exit_price = 0.0
            exit_idx = i
            
            # Update tracking
            high_since = max(high_since, highs[i])
            low_since = min(low_since, lows[i])
            
            current_pnl_pct = (closes[i] - entry_price) / entry_price * 100
            
            # 1. Stop loss (checked against lows[i])
            if lows[i] <= entry_price * (1 - stop_pct / 100):
                exit_reason = "stop_loss"
                exit_price = entry_price * (1 - stop_pct / 100) * (1 - slippage)
            
            # 2. Take profit (checked against highs[i])
            elif highs[i] >= entry_price * (1 + target_pct / 100):
                exit_reason = "take_profit"
                exit_price = entry_price * (1 + target_pct / 100) * (1 - slippage)
            
            # 3. Time exit
            elif hold_bars >= max_hold:
                exit_reason = "time_exit"
                exit_price = opens[i] * (1 - slippage)
            
            # 4. Signal reverse (new Spring signal while holding)
            elif sig[i] == 1 and current_pnl_pct < 0:
                exit_reason = "signal_reverse"
                exit_price = opens[i] * (1 - slippage)
            
            if exit_reason:
                # Gross PnL
                gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
                # Subtract round-trip commission
                net_pnl_pct = gross_pnl_pct - commission * 100
                
                # MFE/MAE
                mfe_pct = (high_since - entry_price) / entry_price * 100
                mae_pct = (low_since - entry_price) / entry_price * 100
                
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": exit_idx,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct": net_pnl_pct,
                    "gross_pnl_pct": gross_pnl_pct,
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "hold_bars": hold_bars,
                    "entry_time": df.index[entry_idx],
                    "exit_time": df.index[exit_idx],
                })
                in_position = False
        
        # (entry check moved above — see ENTRY FIRST section)
    
    # Close any open position at the end
    if in_position:
        exit_idx = n - 1
        hold_bars = exit_idx - entry_idx
        exit_price = closes[exit_idx] * (1 - slippage)
        gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
        net_pnl_pct = gross_pnl_pct - commission * 100
        mfe_pct = (high_since - entry_price) / entry_price * 100
        mae_pct = (low_since - entry_price) / entry_price * 100
        
        trades.append({
            "entry_idx": entry_idx,
            "exit_idx": exit_idx,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "exit_reason": "time_exit",
            "pnl_pct": net_pnl_pct,
            "gross_pnl_pct": gross_pnl_pct,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "hold_bars": hold_bars,
            "entry_time": df.index[entry_idx],
            "exit_time": df.index[exit_idx],
        })
    
    return trades


def compute_metrics(trades):
    """Compute all performance metrics from trade list."""
    if not trades:
        return {"trades": 0, "sharpe": 0, "compound": 0, "sum": 0, 
                "max_dd": 0, "win_rate": 0, "pf": 0, "sortino": 0,
                "avg_win": 0, "avg_loss": 0, "max_consec": 0,
                "annualized": 0}
    
    pnls = [t["pnl_pct"] for t in trades]
    n = len(pnls)
    total_sum = sum(pnls)
    
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    win_rate = len(wins) / n * 100 if n > 0 else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    
    sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(n) if n > 1 and np.std(pnls) > 0 else 0
    
    downside = [p for p in pnls if p < 0]
    sortino = (np.mean(pnls) / np.std(downside) * np.sqrt(n) 
               if downside and n > 1 and np.std(downside) > 0 else 0)
    
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
    
    equity = [10000.0]
    for p in pnls:
        equity.append(equity[-1] * (1 + p / 100))
    equity = np.array(equity)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    max_dd = dd.min()
    
    return {
        "trades": n,
        "compound": compound_return,
        "sum": total_sum,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pf": pf,
        "max_consec": max_consec,
        "annualized": 0,  # will be set by caller
        "wins": wins,
        "losses": losses,
        "pnls": pnls,
    }


def exit_breakdown(trades):
    """Analyze exit reasons."""
    breakdown = {}
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t["exit_reason"] == reason]
        if subset:
            sp = [t["pnl_pct"] for t in subset]
            breakdown[reason] = {
                "count": len(subset),
                "pct": len(subset) / len(trades) * 100,
                "avg": np.mean(sp),
                "total": sum(sp),
            }
    return breakdown


def walk_forward(df, signal, stop_pct, target_pct, max_hold, commission, slippage, n_splits=7):
    """Walk-forward validation with n_splits OOS windows."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        
        split_df = df.iloc[start:end]
        split_sig = signal.iloc[start:end]
        
        t = backtest_spring(split_df, split_sig, stop_pct, target_pct, max_hold,
                           commission, slippage)
        m = compute_metrics(t)
        m["start"] = split_df.index[0]
        m["end"] = split_df.index[-1]
        m["split"] = s + 1
        results.append(m)
    
    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("SPRING REVERSAL — BB FILTER WITHOUT SMA200")
    print("=" * 70)
    
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    
    print(f"\nOKX: {len(df_okx)} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance: {len(df_binance)} bars, {df_binance.index[0]} to {df_binance.index[-1]}")
    
    # Precompute indicators
    for df_label, df in [("OKX", df_okx), ("Binance", df_binance)]:
        print(f"\n[{df_label}] Computing indicators...")
        df["sma200"] = sma(df["close"], 200)
        bb = bollinger_bands(df, 20, 2.0)
        df["bb_pct_b"] = bb["pct_b"]
    
    # ========================================================================
    # CONFIGURATIONS TO TEST
    # ========================================================================
    
    configs = [
        {
            "name": "Baseline (BB [0.12, 0.65) + SMA200)",
            "bb_low": 0.12,
            "bb_high": 0.65,
            "sma200": True,
            "stop": 3.0,
            "target": 2.75,
            "hold": 32,
        },
        {
            "name": "BB [0.12, 0.65) NO SMA200",
            "bb_low": 0.12,
            "bb_high": 0.65,
            "sma200": False,
            "stop": 3.0,
            "target": 2.75,
            "hold": 32,
        },
        {
            "name": "BB [0.10, 0.70) NO SMA200",
            "bb_low": 0.10,
            "bb_high": 0.70,
            "sma200": False,
            "stop": 3.0,
            "target": 2.75,
            "hold": 32,
        },
        {
            "name": "BB [0.05, 0.75) NO SMA200",
            "bb_low": 0.05,
            "bb_high": 0.75,
            "sma200": False,
            "stop": 3.0,
            "target": 2.75,
            "hold": 32,
        },
    ]
    
    all_results = {}
    
    for config in configs:
        name = config["name"]
        print(f"\n{'='*70}")
        print(f"CONFIG: {name}")
        print(f"{'='*70}")
        
        for exchange, df in [("OKX", df_okx), ("Binance", df_binance)]:
            print(f"\n--- {exchange} ---")
            
            # Generate base signal
            base_sig = spring_reversal_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
            
            # Apply BB filter
            bb_low = config["bb_low"]
            bb_high = config["bb_high"]
            bb_filter = (df["bb_pct_b"] >= bb_low) & (df["bb_pct_b"] < bb_high)
            signal = base_sig & bb_filter
            
            # Apply SMA200 filter if enabled
            if config["sma200"]:
                signal = signal & (df["close"] > df["sma200"])
            
            signal_count = signal.sum()
            signal_pct = signal_count / len(df) * 100
            print(f"  Signal count: {signal_count} ({signal_pct:.2f}% of bars)")
            
            # Run backtest
            trades = backtest_spring(
                df, signal,
                stop_pct=config["stop"],
                target_pct=config["target"],
                max_hold=config["hold"],
                commission=0.0005,
                slippage=0.0005,
            )
            
            metrics = compute_metrics(trades)
            
            # Annualized return
            years = (df.index[-1] - df.index[0]).days / 365.25
            metrics["annualized"] = ((1 + metrics["compound"] / 100) ** (1 / years) - 1) * 100 if years > 0 else 0
            
            # Full backtest output
            print(f"\n  Initial Capital:    10,000 USDT")
            print(f"  Commission:         5 bps (round-trip)")
            print(f"  Slippage:           5 bps")
            print(f"")
            print(f"  Total Trades:       {metrics['trades']}")
            print(f"  Compound Return:    {metrics['compound']:+.1f}%")
            print(f"  Annualized Return:  {metrics['annualized']:+.1f}%")
            print(f"  Linear Sum:         {metrics['sum']:+.1f}%")
            print(f"  Sharpe Ratio:       {metrics['sharpe']:+.2f}")
            print(f"  Sortino Ratio:      {metrics['sortino']:+.2f}")
            print(f"  Max Drawdown:       {metrics['max_dd']:+.1f}%")
            print(f"  Win Rate:           {metrics['win_rate']:.1f}%")
            print(f"  Avg Win:            {metrics['avg_win']:+.2f}%")
            print(f"  Avg Loss:           {metrics['avg_loss']:+.2f}%")
            print(f"  Profit Factor:      {metrics['pf']:.2f}")
            print(f"  Max Consec Losses:  {metrics['max_consec']}")
            
            # Exit breakdown
            eb = exit_breakdown(trades)
            print(f"\n  Exit Breakdown:")
            for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
                if reason in eb:
                    r = eb[reason]
                    print(f"    {reason:15s}: {r['count']:4d} ({r['pct']:5.1f}%)  avg={r['avg']:+.2f}%  total={r['total']:+.1f}%")
            
            # MFE
            mfes = [t["mfe_pct"] for t in trades]
            print(f"\n  MFE: mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%  max={np.max(mfes):+.2f}%")
            
            time_ex = [t for t in trades if t["exit_reason"] == "time_exit"]
            if time_ex:
                profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
                print(f"  Time-exits profitable at some point: {profitable_time}/{len(time_ex)} ({profitable_time/len(time_ex)*100:.1f}%)")
            
            # Walk-forward
            wf_results = walk_forward(
                df, signal,
                config["stop"], config["target"], config["hold"],
                0.0005, 0.0005, n_splits=7
            )
            
            wf_positive = sum(1 for r in wf_results if r["sum"] > 0)
            wf_sharpes = [r["sharpe"] for r in wf_results]
            
            print(f"\n  Walk-Forward (7 splits, OOS):")
            for r in wf_results:
                status = "✅" if r["sum"] > 0 else "❌"
                print(f"    Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  "
                      f"trades={r['trades']:3d}  sum={r['sum']:+.1f}%  sharpe={r['sharpe']:+.2f}  {status}")
            print(f"    OOS Profitable: {wf_positive}/{len(wf_results)} splits")
            print(f"    Mean OOS Sharpe: {np.mean(wf_sharpes):+.2f}")
            print(f"    Total OOS Sum: {sum(r['sum'] for r in wf_results):+.1f}%")
            
            # Store for comparison
            key = f"{name} | {exchange}"
            all_results[key] = {
                "config": config,
                "metrics": metrics,
                "trades": trades,
                "wf_results": wf_results,
                "signal_count": signal_count,
            }
    
    # ========================================================================
    # SUMMARY COMPARISON
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"SUMMARY COMPARISON")
    print(f"{'='*70}")
    
    for exchange in ["OKX", "Binance"]:
        print(f"\n--- {exchange} ---")
        print(f"  {'Config':35s} {'Trades':>7s} {'Sharpe':>7s} {'Sum':>8s} {'MaxDD':>7s} {'WF':>6s} {'MeanOOS':>8s}")
        print(f"  {'-'*80}")
        
        for config in configs:
            key = f"{config['name']} | {exchange}"
            if key in all_results:
                r = all_results[key]
                m = r["metrics"]
                wf_pos = sum(1 for w in r["wf_results"] if w["sum"] > 0)
                wf_total = len(r["wf_results"])
                mean_oos = np.mean([w["sharpe"] for w in r["wf_results"]])
                
                print(f"  {config['name']:35s} {m['trades']:7d} {m['sharpe']:+7.2f} {m['sum']:+8.1f}% {m['max_dd']:+7.1f}% {wf_pos}/{wf_total} {mean_oos:+8.2f}")
    
    # ========================================================================
    # TRADE COUNT VS SHARPE: ALL CONFIGS
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"TRADE COUNT VS SHARPE (OKX)")
    print(f"{'='*70}")
    
    for config in configs:
        key = f"{config['name']} | OKX"
        if key in all_results:
            r = all_results[key]
            m = r["metrics"]
            print(f"  {config['name']:35s}: {m['trades']:4d} trades, Sharpe={m['sharpe']:+.2f}, MaxDD={m['max_dd']:+.1f}%, WF={sum(1 for w in r['wf_results'] if w['sum'] > 0)}/{len(r['wf_results'])}")
    
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
