"""
Spring Reversal — Exit Optimization with Lower Targets
======================================================

Research Question: The Spring filtered strategy (SMA200 + BB 0.2-0.6) has Sharpe +1.53
but 70% time-exits with avg +0.10%. Mean MFE is +1.56%. This is the classic
"lower the target" pattern — the 3.0% target is still too high.

Hypothesis: Lowering the target from 3.0% to 1.0-2.0% will:
1. Increase take-profit rate (currently 19.2%)
2. Reduce time-exit rate (currently 70.5%)
3. Improve Sharpe by capturing more of the typical +1-2% bounce

Methodology:
1. Grid search: 8 stops × 11 targets × 8 holds = 704 combinations
2. Focus on lower targets (1.0% to 3.0%)
3. Walk-forward validate best configurations
4. Cross-validate on Binance
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import sma, bollinger_bands


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


def run_backtest(df, signal_series, stop_pct, target_pct, max_hold,
                 commission=0.0005, slippage=0.0005):
    """Run backtest with lows-based stop checking."""
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(df)
    
    trades = []
    position = None
    pending_signal = False
    
    for i in range(n):
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
        
        if position is None and signal_series.iloc[i] == 1:
            pending_signal = True
        
        if position is not None:
            position["bars_held"] += 1
            position["high_since_entry"] = max(position["high_since_entry"], highs[i])
            position["low_since_entry"] = min(position["low_since_entry"], lows[i])
            
            exit_reason = None
            exit_price = None
            
            if lows[i] <= position["stop_price"]:
                exit_reason = "stop_loss"
                exit_price = position["stop_price"] * (1 - slippage)
            elif highs[i] >= position["target_price"]:
                exit_reason = "take_profit"
                exit_price = position["target_price"] * (1 - slippage)
            elif position["bars_held"] >= position["max_hold"]:
                exit_reason = "time_exit"
                exit_price = closes[i]
            
            if exit_reason is not None:
                pnl_pct = (exit_price / position["entry_price"] - 1) * 100
                pnl_pct -= commission * 100
                
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
    
    return {
        "trades": len(trades),
        "sum": sum(pnls),
        "compound": compound_return,
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


def main():
    print("=" * 80)
    print("Spring Reversal — Exit Optimization with Lower Targets")
    print("=" * 80)
    
    # Load data
    print("\n[1/5] Loading data...")
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"  OKX: {len(df_okx)} bars")
    print(f"  Binance: {len(df_binance)} bars")
    
    # Compute signals with filters
    print("\n[2/5] Computing Spring filtered signal...")
    spring_raw = spring_signal(df_okx, lookback=20, vol_mult=1.5, close_pct=0.5)
    sma200 = sma(df_okx["close"], 200)
    bb = bollinger_bands(df_okx, period=20, std=2.0)
    
    # Filter: SMA200 + BB %B 0.2-0.6
    spring_filtered = spring_raw & (df_okx["close"] > sma200) & \
                      (bb["pct_b"] >= 0.2) & (bb["pct_b"] < 0.6)
    
    # Same for Binance
    spring_raw_b = spring_signal(df_binance, lookback=20, vol_mult=1.5, close_pct=0.5)
    sma200_b = sma(df_binance["close"], 200)
    bb_b = bollinger_bands(df_binance, period=20, std=2.0)
    spring_filtered_b = spring_raw_b & (df_binance["close"] > sma200_b) & \
                         (bb_b["pct_b"] >= 0.2) & (bb_b["pct_b"] < 0.6)
    
    print(f"  Spring raw signals:    {spring_raw.sum()}")
    print(f"  Spring filtered:       {spring_filtered.sum()}")
    print(f"  Spring filtered (BNB): {spring_filtered_b.sum()}")
    
    # Baseline
    print("\n[3/5] Baseline (from prior research: s3.0/t3.0/h16)...")
    baseline_trades = run_backtest(df_okx, spring_filtered, stop_pct=3.0, target_pct=3.0, max_hold=16)
    baseline_m = compute_metrics(baseline_trades)
    baseline_eb = exit_breakdown(baseline_trades)
    print(f"  Trades: {baseline_m['trades']}, Sum: {baseline_m['sum']:+.1f}%, Sharpe: {baseline_m['sharpe']:+.2f}")
    print(f"  MaxDD: {baseline_m['max_dd']:.1f}%, WR: {baseline_m['win_rate']:.1f}%, PF: {baseline_m['pf']:.2f}")
    for reason, stats in baseline_eb.items():
        print(f"  {reason:15s}: {stats['count']:>3d} ({stats['pct']:5.1f}%)  avg={stats['avg_pnl']:>+7.2f}%  total={stats['total_pnl']:>+8.1f}%")
    
    # MFE analysis
    mfe_values = [t["mfe_pct"] for t in baseline_trades]
    print(f"\n  MFE: mean={np.mean(mfe_values):+.2f}%, median={np.median(mfe_values):+.2f}%, "
          f"max={np.max(mfe_values):+.2f}%")
    print(f"  Time-exits profitable at some point: "
          f"{sum(1 for t in baseline_trades if t['exit_reason']=='time_exit' and t['mfe_pct']>0)}/"
          f"{sum(1 for t in baseline_trades if t['exit_reason']=='time_exit')}")
    
    # Grid search: lower targets
    print("\n[4/5] Grid search: exit optimization (lower targets)...")
    
    stops = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    targets = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0]
    holds = [8, 10, 12, 14, 16, 20, 24, 32]
    
    all_configs = []
    for stop in stops:
        for target in targets:
            for hold in holds:
                trades = run_backtest(df_okx, spring_filtered, stop_pct=stop, target_pct=target, max_hold=hold)
                m = compute_metrics(trades)
                all_configs.append({
                    "stop": stop, "target": target, "hold": hold,
                    "trades": m["trades"], "sum": m["sum"], "sharpe": m["sharpe"],
                    "max_dd": m["max_dd"], "win_rate": m["win_rate"],
                    "pf": m["pf"], "compound": m["compound"],
                })
    
    # Sort by Sharpe
    all_configs.sort(key=lambda x: x["sharpe"], reverse=True)
    
    print(f"\n  Top 20 by Sharpe:")
    print(f"  {'Stop':>5s} {'Target':>7s} {'Hold':>5s} {'Trades':>6s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print(f"  {'-'*65}")
    for c in all_configs[:20]:
        print(f"  {c['stop']:>4.1f}% {c['target']:>6.2f}% {c['hold']:>4d}h {c['trades']:>6d} {c['sum']:>+7.1f}% {c['sharpe']:>+7.2f} {c['max_dd']:>+6.1f}% {c['win_rate']:>5.1f}% {c['pf']:>5.2f}")
    
    # Walk-forward validate top 3 configurations
    print("\n[5/5] Walk-forward validation of top configurations...")
    
    top_configs = all_configs[:5]
    
    for rank, c in enumerate(top_configs):
        name = f"Config {rank+1}: s{c['stop']:.1f}/t{c['target']:.2f}/h{c['hold']}"
        params = {"stop_pct": c["stop"], "target_pct": c["target"], "max_hold": c["hold"]}
        
        # OKX WF
        wf_okx = walk_forward(df_okx, spring_filtered, params, n_splits=7)
        profitable_okx = sum(1 for s in wf_okx if s["sum"] > 0)
        sharpe_okx = np.mean([s["sharpe"] for s in wf_okx])
        
        # Binance WF
        wf_binance = walk_forward(df_binance, spring_filtered_b, params, n_splits=7)
        profitable_binance = sum(1 for s in wf_binance if s["sum"] > 0)
        sharpe_binance = np.mean([s["sharpe"] for s in wf_binance])
        
        print(f"\n  {name}:")
        print(f"    OKX WF: {profitable_okx}/7 profitable, Mean Sharpe: {sharpe_okx:+.2f}")
        for r in wf_okx:
            status = "✅" if r["sum"] > 0 else "❌"
            print(f"      Split {r['split']}: {str(r['start'])[:10]}→{str(r['end'])[:10]}  "
                  f"t={r['trades']:>2d}  sum={r['sum']:>+6.1f}%  sharpe={r['sharpe']:>+6.2f}  {status}")
        
        print(f"    Binance WF: {profitable_binance}/7 profitable, Mean Sharpe: {sharpe_binance:+.2f}")
        for r in wf_binance:
            status = "✅" if r["sum"] > 0 else "❌"
            print(f"      Split {r['split']}: {str(r['start'])[:10]}→{str(r['end'])[:10]}  "
                  f"t={r['trades']:>2d}  sum={r['sum']:>+6.1f}%  sharpe={r['sharpe']:>+6.2f}  {status}")
    
    # Best config detailed breakdown
    best = all_configs[0]
    print(f"\n{'='*80}")
    print(f"BEST CONFIGURATION: stop={best['stop']:.1f}%, target={best['target']:.2f}%, hold={best['hold']}h")
    print(f"{'='*80}")
    
    best_trades = run_backtest(df_okx, spring_filtered, 
                                stop_pct=best["stop"], target_pct=best["target"], max_hold=best["hold"])
    best_m = compute_metrics(best_trades)
    best_eb = exit_breakdown(best_trades)
    
    print(f"\n  Full Backtest (OKX BTC/USDT 1h, 2019-2026):")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {best_m['trades']}")
    print(f"  Compound Return:    {best_m['compound']:+.1f}%")
    print(f"  Linear Sum:         {best_m['sum']:+.1f}%")
    print(f"  Sharpe Ratio:       {best_m['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {best_m['sortino']:+.2f}")
    print(f"  Max Drawdown:       {best_m['max_dd']:.1f}%")
    print(f"  Win Rate:           {best_m['win_rate']:.1f}%")
    print(f"  Avg Win:            {best_m['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {best_m['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {best_m['pf']:.2f}")
    print(f"  Max Consec Losses:  {best_m['max_consec']}")
    print(f"")
    print(f"  Exit Breakdown:")
    for reason, stats in best_eb.items():
        print(f"    {reason:15s}: {stats['count']:>3d} ({stats['pct']:5.1f}%)  avg={stats['avg_pnl']:>+7.2f}%  total={stats['total_pnl']:>+8.1f}%")
    
    # Comparison with baseline
    print(f"\n  Comparison with Baseline (s3.0/t3.0/h16):")
    print(f"  {'Metric':20s} {'Baseline':>10s} {'Optimized':>10s} {'Delta':>10s}")
    print(f"  {'-'*50}")
    print(f"  {'Sharpe':20s} {baseline_m['sharpe']:>+9.2f} {best_m['sharpe']:>+9.2f} {best_m['sharpe']-baseline_m['sharpe']:>+9.2f}")
    print(f"  {'Sum':20s} {baseline_m['sum']:>+9.1f}% {best_m['sum']:>+9.1f}% {best_m['sum']-baseline_m['sum']:>+9.1f}%")
    print(f"  {'Compound':20s} {baseline_m['compound']:>+9.1f}% {best_m['compound']:>+9.1f}% {best_m['compound']-baseline_m['compound']:>+9.1f}%")
    print(f"  {'Max DD':20s} {baseline_m['max_dd']:>+9.1f}% {best_m['max_dd']:>+9.1f}% {best_m['max_dd']-baseline_m['max_dd']:>+9.1f}%")
    print(f"  {'Win Rate':20s} {baseline_m['win_rate']:>+9.1f}% {best_m['win_rate']:>+9.1f}% {best_m['win_rate']-baseline_m['win_rate']:>+9.1f}%")
    print(f"  {'PF':20s} {baseline_m['pf']:>9.2f} {best_m['pf']:>9.2f} {best_m['pf']-baseline_m['pf']:>+9.2f}")
    print(f"  {'Trades':20s} {baseline_m['trades']:>9d} {best_m['trades']:>9d} {best_m['trades']-baseline_m['trades']:>+9d}")
    
    print("\nDone.")


if __name__ == "__main__":
    main()
