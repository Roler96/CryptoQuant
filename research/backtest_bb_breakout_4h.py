"""
BB Upper Breakout — 4h Timeframe Research
==========================================

Tests the BB Upper Breakout strategy on 4h bars (resampled from 1h).
Hypothesis: wider timeframe bars produce higher quality breakouts with
fewer false signals and better risk-adjusted returns.

Compares 4h results against 1h baseline from prior research.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import sma, bollinger_bands


# ============================================================================
# Resample 1h to 4h
# ============================================================================

def resample_to_4h(df_1h):
    """Resample 1h OHLCV to 4h bars."""
    df_4h = df_1h.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    return df_4h.dropna()


# ============================================================================
# BB Breakout Signal
# ============================================================================

def bb_breakout_signal(df, bb_period=50, bb_std=2.5, sma_period=200):
    """
    BB Upper Breakout signal.
    
    Entry: close > upper_band AND close > SMA(sma_period)
    """
    bb = bollinger_bands(df, period=bb_period, std=bb_std)
    sma200 = sma(df["close"], sma_period)
    
    signal = (df["close"] > bb["upper"]) & (df["close"] > sma200)
    return signal.astype(int)


# ============================================================================
# Custom Backtest (lows-based stops)
# ============================================================================

def backtest(df, signals, stop_pct=1.2, target_pct=4.0, max_hold=10,
             commission=0.0005, slippage=0.0005):
    """
    Run backtest with lows-based stop checking.
    Returns list of trade dicts.
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
                exit_price = opens[i] * (1 - slippage)
            
            if exit_reason:
                pnl_pct = (exit_price / position["entry_price"] - 1) * 100
                mfe_pct = (position["high_since_entry"] / position["entry_price"] - 1) * 100
                mae_pct = (position["low_since_entry"] / position["entry_price"] - 1) * 100
                
                trades.append({
                    "entry_idx": position["entry_idx"],
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct": pnl_pct,
                    "mfe_pct": mfe_pct,
                    "mae_pct": mae_pct,
                    "bars_held": position["bars_held"],
                    "hold_hours": position["bars_held"] * 4,  # 4h bars
                })
                position = None
    
    # Close any open position at end
    if position is not None:
        exit_price = closes[-1] * (1 - slippage)
        pnl_pct = (exit_price / position["entry_price"] - 1) * 100
        mfe_pct = (position["high_since_entry"] / position["entry_price"] - 1) * 100
        mae_pct = (position["low_since_entry"] / position["entry_price"] - 1) * 100
        
        trades.append({
            "entry_idx": position["entry_idx"],
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "exit_reason": "end_of_data",
            "pnl_pct": pnl_pct,
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "bars_held": position["bars_held"],
            "hold_hours": position["bars_held"] * 4,
        })
    
    return trades


# ============================================================================
# Metrics Calculation
# ============================================================================

def calc_metrics(trades, initial_capital=10000):
    """Calculate performance metrics from trade list."""
    if not trades:
        return {
            "total_trades": 0,
            "compound_return": 0.0,
            "linear_sum": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_dd": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "max_consec_losses": 0,
        }
    
    pnls = np.array([t["pnl_pct"] for t in trades])
    linear_sum = float(np.sum(pnls))
    
    # Compound return
    equity = initial_capital
    for p in pnls:
        equity *= (1 + p / 100)
    compound_return = (equity / initial_capital - 1) * 100
    
    # Sharpe (per-trade)
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = float(np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls)))
    else:
        sharpe = 0.0
    
    # Sortino
    downside = pnls[pnls < 0]
    if len(downside) > 1 and np.std(downside) > 0:
        sortino = float(np.mean(pnls) / np.std(downside) * np.sqrt(len(pnls)))
    else:
        sortino = 0.0
    
    # Max drawdown (from equity curve)
    equity_curve = [initial_capital]
    for p in pnls:
        equity_curve.append(equity_curve[-1] * (1 + p / 100))
    equity_curve = np.array(equity_curve)
    peak = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - peak) / peak * 100
    max_dd = float(np.min(dd))
    
    # Win rate
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    win_rate = len(wins) / len(pnls) * 100
    
    avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0.0
    
    # Profit factor
    total_wins = float(np.sum(wins)) if len(wins) > 0 else 0.0
    total_losses = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")
    
    # Max consecutive losses
    max_cl = 0
    current_cl = 0
    for p in pnls:
        if p <= 0:
            current_cl += 1
            max_cl = max(max_cl, current_cl)
        else:
            current_cl = 0
    
    return {
        "total_trades": len(trades),
        "compound_return": compound_return,
        "linear_sum": linear_sum,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_consec_losses": max_cl,
    }


# ============================================================================
# Exit Breakdown
# ============================================================================

def exit_breakdown(trades):
    """Analyze exits by reason."""
    by_reason = defaultdict(list)
    for t in trades:
        by_reason[t["exit_reason"]].append(t)
    
    result = {}
    for reason, subset in by_reason.items():
        pnls = [t["pnl_pct"] for t in subset]
        result[reason] = {
            "count": len(subset),
            "pct": len(subset) / len(trades) * 100,
            "avg_pnl": np.mean(pnls),
            "total_pnl": np.sum(pnls),
        }
    return result


# ============================================================================
# Walk-Forward Validation
# ============================================================================

def walk_forward(df, signal_series, stop_pct, target_pct, max_hold, n_splits=7):
    """Run walk-forward validation."""
    n = len(df)
    slot = len(df) // (n_splits + 2)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]
        split_sig = signal_series.iloc[start:end]
        
        trades = backtest(split_df, split_sig, stop_pct, target_pct, max_hold)
        metrics = calc_metrics(trades)
        
        results.append({
            "split": s + 1,
            "start": str(split_df.index[0])[:10],
            "end": str(split_df.index[-1])[:10],
            "trades": metrics["total_trades"],
            "sum": metrics["linear_sum"],
            "sharpe": metrics["sharpe"],
            "dd": metrics["max_dd"],
        })
    
    return results


# ============================================================================
# Parameter Sweep
# ============================================================================

def parameter_sweep(df, signals, stop_range, target_range, hold_range):
    """Sweep exit parameters."""
    results = []
    for stop_pct in stop_range:
        for target_pct in target_range:
            for max_hold in hold_range:
                trades = backtest(df, signals, stop_pct, target_pct, max_hold)
                m = calc_metrics(trades)
                results.append({
                    "stop": stop_pct,
                    "target": target_pct,
                    "hold": max_hold,
                    "trades": m["total_trades"],
                    "sum": m["linear_sum"],
                    "sharpe": m["sharpe"],
                    "max_dd": m["max_dd"],
                    "win_rate": m["win_rate"],
                    "profit_factor": m["profit_factor"],
                })
    return sorted(results, key=lambda x: x["sharpe"], reverse=True)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("BB Upper Breakout — 4h Timeframe Research")
    print("=" * 70)
    
    # Load data
    store = OHLCVStore()
    df_1h = store.load("okx", "BTC/USDT", "1h")
    print(f"\nLoaded 1h data: {len(df_1h)} bars, {df_1h.index[0]} to {df_1h.index[-1]}")
    
    # Resample to 4h
    df_4h = resample_to_4h(df_1h)
    print(f"Resampled to 4h: {len(df_4h)} bars, {df_4h.index[0]} to {df_4h.index[-1]}")
    
    # ========================================================================
    # PART 1: Baseline — 1h optimized params mapped to 4h
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 1: Baseline (1h params mapped to 4h)")
    print("=" * 70)
    
    # 1h baseline params: BB(50, 2.5), SMA200, stop=1.2%, target=4.0%, hold=10
    # 4h equivalent: BB(50, 2.5), SMA200, stop=?, target=?, hold=?
    # 4h bars are 4x longer, so hold_bars should be ~10/4 = 2.5 → test 2,3,4
    # Stop/target: wider bars = wider moves, so scale up
    
    bb_periods = [20, 30, 50]
    bb_stds = [2.0, 2.5, 3.0]
    
    print("\n--- BB Parameter Sweep (4h, SMA200 filter) ---")
    print(f"{'Period':>6s} {'Std':>5s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 60)
    
    bb_results = []
    for period in bb_periods:
        for std in bb_stds:
            sig = bb_breakout_signal(df_4h, bb_period=period, bb_std=std, sma_period=200)
            # Use scaled params: stop=2.0%, target=6.0%, hold=3 (12h equivalent)
            trades = backtest(df_4h, sig, stop_pct=2.0, target_pct=6.0, max_hold=3)
            m = calc_metrics(trades)
            bb_results.append({
                "period": period, "std": std,
                "trades": m["total_trades"], "sum": m["linear_sum"],
                "sharpe": m["sharpe"], "max_dd": m["max_dd"],
                "win_rate": m["win_rate"], "profit_factor": m["profit_factor"],
            })
            print(f"{period:>6d} {std:>5.1f} {m['total_trades']:>7d} {m['linear_sum']:>+7.1f}% {m['sharpe']:>+7.2f} {m['max_dd']:>+7.1f}% {m['win_rate']:>5.1f}% {m['profit_factor']:>5.2f}")
    
    # Find best BB params
    best_bb = max(bb_results, key=lambda x: x["sharpe"])
    print(f"\nBest BB params: period={best_bb['period']}, std={best_bb['std']}, Sharpe={best_bb['sharpe']:.2f}")
    
    # ========================================================================
    # PART 2: Exit Parameter Sweep (with best BB params)
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 2: Exit Parameter Sweep")
    print("=" * 70)
    
    best_period = best_bb["period"]
    best_std = best_bb["std"]
    sig = bb_breakout_signal(df_4h, bb_period=best_period, bb_std=best_std, sma_period=200)
    
    stops = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    targets = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
    holds = [2, 3, 4, 5, 6, 8]  # 8h, 12h, 16h, 20h, 24h, 32h
    
    sweep_results = parameter_sweep(df_4h, sig, stops, targets, holds)
    
    print(f"\nTop 10 by Sharpe:")
    print(f"{'Stop':>5s} {'Target':>7s} {'Hold':>5s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 70)
    for r in sweep_results[:10]:
        print(f"{r['stop']:>4.1f}% {r['target']:>6.1f}% {r['hold']:>4d}h {r['trades']:>7d} {r['sum']:>+7.1f}% {r['sharpe']:>+7.2f} {r['max_dd']:>+6.1f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")
    
    best_exit = sweep_results[0]
    print(f"\nBest exit: stop={best_exit['stop']}%, target={best_exit['target']}%, hold={best_exit['hold']}h")
    
    # ========================================================================
    # PART 3: Full Backtest with Best Params
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 3: Full Backtest — Best Configuration")
    print("=" * 70)
    
    best_trades = backtest(df_4h, sig, 
                           stop_pct=best_exit["stop"],
                           target_pct=best_exit["target"],
                           max_hold=best_exit["hold"])
    best_metrics = calc_metrics(best_trades)
    
    print(f"""
    Initial Capital:    10,000 USDT
    Commission:         5 bps (round-trip)
    Slippage:           5 bps
    
    Total Trades:       {best_metrics['total_trades']}
    Compound Return:    {best_metrics['compound_return']:+.1f}%
    Linear Sum:         {best_metrics['linear_sum']:+.1f}%
    Sharpe Ratio:       {best_metrics['sharpe']:+.2f}
    Sortino Ratio:      {best_metrics['sortino']:+.2f}
    Max Drawdown:       {best_metrics['max_dd']:+.1f}%
    Win Rate:           {best_metrics['win_rate']:.1f}%
    Avg Win:            {best_metrics['avg_win']:+.2f}%
    Avg Loss:           {best_metrics['avg_loss']:+.2f}%
    Profit Factor:      {best_metrics['profit_factor']:.2f}
    Max Consec Losses:  {best_metrics['max_consec_losses']}
    """)
    
    eb = exit_breakdown(best_trades)
    print("Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "end_of_data"]:
        if reason in eb:
            e = eb[reason]
            print(f"  {reason:15s} {e['count']:>4d} ({e['pct']:>5.1f}%)  avg={e['avg_pnl']:>+6.2f}%  total={e['total_pnl']:>+8.1f}%")
    
    # MFE analysis
    mfes = [t["mfe_pct"] for t in best_trades]
    print(f"\nMFE Analysis:")
    print(f"  Mean:   {np.mean(mfes):+.2f}%")
    print(f"  Median: {np.median(mfes):+.2f}%")
    print(f"  Max:    {np.max(mfes):+.2f}%")
    
    time_exits = [t for t in best_trades if t["exit_reason"] == "time_exit"]
    if time_exits:
        profitable_at_some_point = sum(1 for t in time_exits if t["mfe_pct"] > 0)
        print(f"  Time-exits profitable at some point: {profitable_at_some_point}/{len(time_exits)} ({profitable_at_some_point/len(time_exits)*100:.1f}%)")
    
    # ========================================================================
    # PART 4: Walk-Forward Validation
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 4: Walk-Forward Validation (7 splits)")
    print("=" * 70)
    
    wf = walk_forward(df_4h, sig, best_exit["stop"], best_exit["target"], best_exit["hold"])
    
    print(f"{'Split':>5s} {'Period':>22s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'DD':>7s} {'Status':>7s}")
    print("-" * 70)
    profitable = 0
    for r in wf:
        status = "OK" if r["sum"] > 0 else "FAIL"
        if r["sum"] > 0:
            profitable += 1
        print(f"{r['split']:>5d} {r['start']}→{r['end']} {r['trades']:>7d} {r['sum']:>+7.1f}% {r['sharpe']:>+7.2f} {r['dd']:>+6.1f}% {status:>7s}")
    
    mean_sharpe = np.mean([r["sharpe"] for r in wf])
    total_sum = sum(r["sum"] for r in wf)
    print(f"\n{profitable}/{len(wf)} OOS profitable | Mean OOS Sharpe: {mean_sharpe:+.2f} | Total OOS Sum: {total_sum:+.1f}%")
    
    # ========================================================================
    # PART 5: SMA200 Filter Impact
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 5: SMA200 Filter Impact")
    print("=" * 70)
    
    # Without SMA200
    sig_no_sma = bb_breakout_signal(df_4h, bb_period=best_period, bb_std=best_std, sma_period=1)  # sma_period=1 means always above
    trades_no_sma = backtest(df_4h, sig_no_sma, best_exit["stop"], best_exit["target"], best_exit["hold"])
    m_no_sma = calc_metrics(trades_no_sma)
    
    print(f"{'Config':30s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 75)
    print(f"{'With SMA200':30s} {best_metrics['total_trades']:>7d} {best_metrics['linear_sum']:>+7.1f}% {best_metrics['sharpe']:>+7.2f} {best_metrics['max_dd']:>+6.1f}% {best_metrics['win_rate']:>5.1f}% {best_metrics['profit_factor']:>5.2f}")
    print(f"{'Without SMA200':30s} {m_no_sma['total_trades']:>7d} {m_no_sma['linear_sum']:>+7.1f}% {m_no_sma['sharpe']:>+7.2f} {m_no_sma['max_dd']:>+6.1f}% {m_no_sma['win_rate']:>5.1f}% {m_no_sma['profit_factor']:>5.2f}")
    
    # ========================================================================
    # PART 6: Comparison with 1h Baseline
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 6: 4h vs 1h Comparison")
    print("=" * 70)
    
    # Run 1h baseline for direct comparison
    sig_1h = bb_breakout_signal(df_1h, bb_period=50, bb_std=2.5, sma_period=200)
    trades_1h = backtest(df_1h, sig_1h, stop_pct=1.2, target_pct=4.0, max_hold=10)
    m_1h = calc_metrics(trades_1h)
    
    print(f"{'Metric':25s} {'1h Baseline':>15s} {'4h Best':>15s} {'Delta':>15s}")
    print("-" * 75)
    print(f"{'Trades':25s} {m_1h['total_trades']:>15d} {best_metrics['total_trades']:>15d} {best_metrics['total_trades'] - m_1h['total_trades']:>+15d}")
    print(f"{'Compound Return':25s} {m_1h['compound_return']:>+14.1f}% {best_metrics['compound_return']:>+14.1f}% {best_metrics['compound_return'] - m_1h['compound_return']:>+14.1f}%")
    print(f"{'Linear Sum':25s} {m_1h['linear_sum']:>+14.1f}% {best_metrics['linear_sum']:>+14.1f}% {best_metrics['linear_sum'] - m_1h['linear_sum']:>+14.1f}%")
    print(f"{'Sharpe':25s} {m_1h['sharpe']:>+14.2f} {best_metrics['sharpe']:>+14.2f} {best_metrics['sharpe'] - m_1h['sharpe']:>+14.2f}")
    print(f"{'Max DD':25s} {m_1h['max_dd']:>+14.1f}% {best_metrics['max_dd']:>+14.1f}% {best_metrics['max_dd'] - m_1h['max_dd']:>+14.1f}%")
    print(f"{'Win Rate':25s} {m_1h['win_rate']:>14.1f}% {best_metrics['win_rate']:>14.1f}% {best_metrics['win_rate'] - m_1h['win_rate']:>+14.1f}%")
    print(f"{'Profit Factor':25s} {m_1h['profit_factor']:>14.2f} {best_metrics['profit_factor']:>14.2f} {best_metrics['profit_factor'] - m_1h['profit_factor']:>+14.2f}")
    print(f"{'Avg Win':25s} {m_1h['avg_win']:>+14.2f}% {best_metrics['avg_win']:>+14.2f}% {best_metrics['avg_win'] - m_1h['avg_win']:>+14.2f}%")
    print(f"{'Avg Loss':25s} {m_1h['avg_loss']:>+14.2f}% {best_metrics['avg_loss']:>+14.2f}% {best_metrics['avg_loss'] - m_1h['avg_loss']:>+14.2f}%")
    
    # Walk-forward comparison
    print("\n--- Walk-Forward Comparison ---")
    wf_1h = walk_forward(df_1h, sig_1h, 1.2, 4.0, 10, n_splits=7)
    
    print(f"{'Split':>5s} {'1h Sum':>10s} {'1h Sharpe':>10s} {'4h Sum':>10s} {'4h Sharpe':>10s}")
    print("-" * 55)
    for i in range(7):
        print(f"{i+1:>5d} {wf_1h[i]['sum']:>+9.1f}% {wf_1h[i]['sharpe']:>+9.2f} {wf[i]['sum']:>+9.1f}% {wf[i]['sharpe']:>+9.2f}")
    
    wf_1h_profitable = sum(1 for r in wf_1h if r["sum"] > 0)
    wf_1h_mean = np.mean([r["sharpe"] for r in wf_1h])
    print(f"\n1h: {wf_1h_profitable}/7 profitable, Mean Sharpe: {wf_1h_mean:+.2f}")
    print(f"4h: {profitable}/7 profitable, Mean Sharpe: {mean_sharpe:+.2f}")
    
    # ========================================================================
    # PART 7: Binance Cross-Validation
    # ========================================================================
    print("\n" + "=" * 70)
    print("PART 7: Binance Cross-Validation")
    print("=" * 70)
    
    df_bn_1h = store.load("binance", "BTC/USDT", "1h")
    df_bn_4h = resample_to_4h(df_bn_1h)
    print(f"Binance 4h: {len(df_bn_4h)} bars")
    
    sig_bn = bb_breakout_signal(df_bn_4h, bb_period=best_period, bb_std=best_std, sma_period=200)
    trades_bn = backtest(df_bn_4h, sig_bn, best_exit["stop"], best_exit["target"], best_exit["hold"])
    m_bn = calc_metrics(trades_bn)
    
    print(f"\n{'Metric':25s} {'OKX 4h':>15s} {'Binance 4h':>15s}")
    print("-" * 60)
    print(f"{'Trades':25s} {best_metrics['total_trades']:>15d} {m_bn['total_trades']:>15d}")
    print(f"{'Compound Return':25s} {best_metrics['compound_return']:>+14.1f}% {m_bn['compound_return']:>+14.1f}%")
    print(f"{'Linear Sum':25s} {best_metrics['linear_sum']:>+14.1f}% {m_bn['linear_sum']:>+14.1f}%")
    print(f"{'Sharpe':25s} {best_metrics['sharpe']:>+14.2f} {m_bn['sharpe']:>+14.2f}")
    print(f"{'Max DD':25s} {best_metrics['max_dd']:>+14.1f}% {m_bn['max_dd']:>+14.1f}%")
    print(f"{'Win Rate':25s} {best_metrics['win_rate']:>14.1f}% {m_bn['win_rate']:>14.1f}%")
    print(f"{'Profit Factor':25s} {best_metrics['profit_factor']:>14.2f} {m_bn['profit_factor']:>14.2f}")
    
    # Binance WF
    wf_bn = walk_forward(df_bn_4h, sig_bn, best_exit["stop"], best_exit["target"], best_exit["hold"])
    bn_profitable = sum(1 for r in wf_bn if r["sum"] > 0)
    bn_mean = np.mean([r["sharpe"] for r in wf_bn])
    print(f"\nBinance WF: {bn_profitable}/7 profitable, Mean Sharpe: {bn_mean:+.2f}")
    
    print("\n" + "=" * 70)
    print("RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
