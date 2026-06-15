"""
Spring Reversal — Trend Filter Comparison
==========================================

Quick experiment: Compare SMA200, SMA50, EMA50>EMA200, and PDI>MDI
as trend filters for Spring entries (all combined with BB %B 0.2-0.6).

Goal: Find if any filter beats SMA200 for Spring.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import (
    sma, ema, bollinger_bands, adx as adx_func,
    atr as atr_func, rsi, pct_change_rolling,
)


def spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5):
    opens = df["open"]; highs = df["high"]; lows = df["low"]
    closes = df["close"]; volumes = df["volume"]
    rolling_low = lows.rolling(lookback).min().shift(1)
    new_low = lows < rolling_low
    bullish_close = closes > opens
    bar_range = highs - lows
    close_position = (closes - lows) / bar_range.replace(0, np.nan)
    close_near_high = close_position > close_pct
    avg_vol = volumes.rolling(lookback).mean().shift(1)
    high_volume = volumes > (vol_mult * avg_vol)
    return new_low & bullish_close & close_near_high & high_volume


def regime_backtest(df, signals, stop_pct=3.0, target_pct=2.5,
                    max_hold=24, commission=0.0005, slippage=0.0005):
    opens = df["open"].values; highs = df["high"].values
    lows = df["low"].values; closes = df["close"].values
    n = len(df)
    trades = []; position = None; pending_signal = False

    for i in range(n):
        if position is None and pending_signal:
            entry_price = opens[i]; entry_idx = i
            stop_price = entry_price * (1 - stop_pct / 100)
            target_price = entry_price * (1 + target_pct / 100)
            position = {"entry_idx": entry_idx, "entry_price": entry_price,
                        "stop_price": stop_price, "target_price": target_price,
                        "max_hold": max_hold, "bars_held": 0,
                        "high_since_entry": entry_price, "low_since_entry": entry_price}
            pending_signal = False; continue

        if position is None and signals.iloc[i] == 1:
            pending_signal = True

        if position is not None:
            position["bars_held"] += 1
            position["high_since_entry"] = max(position["high_since_entry"], highs[i])
            position["low_since_entry"] = min(position["low_since_entry"], lows[i])
            exit_reason = None; exit_price = None

            if lows[i] <= position["stop_price"]:
                exit_reason = "stop_loss"
                exit_price = position["stop_price"] * (1 - slippage)
            elif highs[i] >= position["target_price"]:
                exit_reason = "take_profit"
                exit_price = position["target_price"] * (1 - slippage)
            elif position["bars_held"] >= position["max_hold"]:
                exit_reason = "time_exit"
                exit_price = closes[i]
            elif signals.iloc[i] == -1:
                exit_reason = "signal_reverse"
                exit_price = closes[i]

            if exit_reason is not None:
                pnl_pct = (exit_price / position["entry_price"] - 1) * 100
                pnl_pct -= commission * 100
                mfe_pct = (position["high_since_entry"] / position["entry_price"] - 1) * 100
                mae_pct = (position["low_since_entry"] / position["entry_price"] - 1) * 100
                trades.append({"pnl_pct": pnl_pct, "mfe_pct": mfe_pct,
                               "mae_pct": mae_pct, "exit_reason": exit_reason,
                               "bars_held": position["bars_held"]})
                position = None; pending_signal = False
    return trades


def compute_metrics(trades):
    if not trades: return {"trades": 0, "total_sum": 0, "sharpe": 0, "max_dd": 0,
                            "win_rate": 0, "pf": 0, "exit_breakdown": {}}
    pnls = [t["pnl_pct"] for t in trades]
    total_sum = sum(pnls)
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    win_rate = len(wins)/len(pnls)*100 if pnls else 0
    sharpe = np.mean(pnls)/np.std(pnls)*np.sqrt(len(pnls)) if len(pnls)>1 and np.std(pnls)>0 else 0
    gp = sum(wins) if wins else 0; gl = abs(sum(losses)) if losses else 1
    pf = gp/gl if gl > 0 else float('inf')
    eq = [10000]
    for p in pnls: eq.append(eq[-1]*(1+p/100))
    eq = np.array(eq)
    dd = (eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq) * 100
    max_dd = dd.min()
    compound = 1.0
    for p in pnls: compound *= (1+p/100)
    compound_return = (compound-1)*100
    ec = Counter(t["exit_reason"] for t in trades)
    exit_detail = {}
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        subset = [t for t in trades if t["exit_reason"]==reason]
        if subset:
            sp = [t["pnl_pct"] for t in subset]
            exit_detail[reason] = {"count": len(subset), "pct": len(subset)/len(trades)*100,
                                    "avg": np.mean(sp), "total": sum(sp)}
    return {"trades": len(trades), "total_sum": total_sum, "sharpe": sharpe,
            "max_dd": max_dd, "win_rate": win_rate, "pf": pf,
            "compound_return": compound_return, "exit_breakdown": exit_detail,
            "pnls": pnls, "trades_list": trades}


def walk_forward_quick(df, signal_series, n_splits=7, **kwargs):
    n = len(df); slot = n // (n_splits + 2); results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot; end = min(n, start + slot)
        split_df = df.iloc[start:end]; split_sig = signal_series.iloc[start:end]
        trades = regime_backtest(split_df, split_sig, **kwargs)
        if trades:
            pnls = [t["pnl_pct"] for t in trades]
            ss = sum(pnls)
            ssh = np.mean(pnls)/np.std(pnls)*np.sqrt(len(pnls)) if len(pnls)>1 and np.std(pnls)>0 else 0
        else:
            ss = 0; ssh = 0
        results.append({"split": s+1, "start": split_df.index[0], "end": split_df.index[-1],
                        "trades": len(trades) if trades else 0, "sum": ss, "sharpe": ssh})
    return results


def main():
    print("=" * 70)
    print("SPRING REVERSAL — TREND FILTER COMPARISON")
    print("=" * 70)

    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nOKX: {len(df)} bars, {df.index[0]} to {df.index[-1]}")

    # Compute indicators
    df["sma200"] = sma(df["close"], 200)
    df["sma50"] = sma(df["close"], 50)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["ema_cross_bull"] = df["ema50"] > df["ema200"]

    adx_df = adx_func(df, 14)
    df["adx"] = adx_df["adx"]
    df["pdi"] = adx_df["pdi"]
    df["mdi"] = adx_df["mdi"]
    df["pdi_gt_mdi"] = df["pdi"] > df["mdi"]

    df["atr14"] = atr_func(df, 14)

    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]
    df["bb_middle"] = bb["middle"]

    spring_sig = spring_signal(df)

    bb_zone = (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)

    base_params = {"stop_pct": 3.0, "target_pct": 2.5, "max_hold": 24,
                   "commission": 0.0005, "slippage": 0.0005}

    print(f"\n  Spring signals:           {spring_sig.sum()}")
    print(f"  BB %B 0.2-0.6 zone:       {bb_zone.sum()}")

    # ========================================================================
    # FILTER COMPARISON
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"FILTER COMPARISON (all with BB %B 0.2-0.6 zone)")
    print(f"{'='*70}")

    filters = [
        ("No trend filter", spring_sig & bb_zone),
        ("SMA200 (baseline)", spring_sig & bb_zone & (df["close"] > df["sma200"])),
        ("SMA50", spring_sig & bb_zone & (df["close"] > df["sma50"])),
        ("SMA100", spring_sig & bb_zone & (df["close"] > sma(df["close"], 100))),
        ("EMA50>EMA200", spring_sig & bb_zone & df["ema_cross_bull"]),
        ("PDI > MDI", spring_sig & bb_zone & df["pdi_gt_mdi"]),
        ("Above BB Middle", spring_sig & bb_zone & (df["close"] > df["bb_middle"])),
        ("SMA200 + PDI>MDI", spring_sig & bb_zone & (df["close"] > df["sma200"]) & df["pdi_gt_mdi"]),
    ]

    print(f"\n{'Filter':<25s} {'Sigs':>6s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s} {'TP%':>6s} {'SL%':>6s} {'TE%':>6s}")
    print("-" * 110)

    best_filter = None
    best_sharpe = -999
    
    all_results = []

    for name, sig in filters:
        trades = regime_backtest(df, sig, **base_params)
        m = compute_metrics(trades)
        all_results.append((name, m, sig))
        
        tp_pct = m["exit_breakdown"].get("take_profit", {}).get("pct", 0)
        sl_pct = m["exit_breakdown"].get("stop_loss", {}).get("pct", 0)
        te_pct = m["exit_breakdown"].get("time_exit", {}).get("pct", 0)

        print(f"  {name:<25s} {sig.sum():>5d}  {m['trades']:5d}   {m['total_sum']:+7.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['pf']:5.2f}  {tp_pct:5.1f}% {sl_pct:5.1f}% {te_pct:5.1f}%")

        if m["sharpe"] > best_sharpe:
            best_sharpe = m["sharpe"]
            best_filter = (name, m, sig)

    # ========================================================================
    # WALK-FORWARD for top 3
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"WALK-FORWARD VALIDATION (top performers)")
    print(f"{'='*70}")

    # Sort by Sharpe and take top 3
    all_results.sort(key=lambda x: x[1]["sharpe"], reverse=True)
    
    for rank, (name, m, sig) in enumerate(all_results[:3], 1):
        print(f"\n  {rank}. {name} (Sharpe={m['sharpe']:+.2f})")
        wf = walk_forward_quick(df, sig, n_splits=7, **base_params)
        wf_pos = sum(1 for r in wf if r["sum"] > 0)
        wf_sharpes = [r["sharpe"] for r in wf]
        total_wf = sum(r["sum"] for r in wf)
        for r in wf:
            status = "✅" if r["sum"] > 0 else "❌"
            print(f"     Split {r['split']}: {r['start'].strftime('%Y-%m')}→{r['end'].strftime('%Y-%m')}  trades={r['trades']:3d}  sum={r['sum']:+6.1f}%  sharpe={r['sharpe']:+6.2f}  {status}")
        print(f"     → {wf_pos}/7 OOS profitable, Mean OOS Sharpe={np.mean(wf_sharpes):+.2f}, Total={total_wf:+.1f}%")

    # ========================================================================
    # Best filter: detailed exit breakdown
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"DETAILED: {best_filter[0]}")
    print(f"{'='*70}")
    m = best_filter[1]
    print(f"  Trades: {m['trades']}")
    print(f"  Compound Return: {m['compound_return']:+.1f}%")
    print(f"  Sharpe: {m['sharpe']:+.2f}")
    print(f"  Max DD: {m['max_dd']:+.1f}%")
    print(f"  Win Rate: {m['win_rate']:.1f}%")
    print(f"  Profit Factor: {m['pf']:.2f}")
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        detail = m["exit_breakdown"].get(reason)
        if detail:
            print(f"    {reason:15s}: {detail['count']:4d} ({detail['pct']:5.1f}%)  avg={detail['avg']:+.2f}%  total={detail['total']:+.1f}%")

    # MFE/MAE
    mfes = [t["mfe_pct"] for t in best_filter[2]["trades_list"]] if "trades_list" in dir(best_filter[2]) else []
    time_ex = [t for t in best_filter[1]["trades_list"] if t["exit_reason"] == "time_exit"]
    if time_ex:
        profitable_time = sum(1 for t in time_ex if t["mfe_pct"] > 0)
        print(f"\n  Time-exits profitable at some point: {profitable_time}/{len(time_ex)} ({profitable_time/len(time_ex)*100:.1f}%)")

    print("\n" + "=" * 70)
    print("RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
