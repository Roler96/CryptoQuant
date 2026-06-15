"""
Spring Reversal — Exit Optimization for EMA50>EMA200 Filter
=============================================================

Quick grid search to see if exit tuning can close the gap between
EMA50>EMA200 filter and SMA200 baseline.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from collections import Counter

from cryptoquant.data.store import OHLCVStore
from cryptoquant.strategy.signals import sma, ema, bollinger_bands

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
    n = len(df); trades = []; position = None; pending_signal = False
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
                exit_reason = "stop_loss"; exit_price = position["stop_price"] * (1 - slippage)
            elif highs[i] >= position["target_price"]:
                exit_reason = "take_profit"; exit_price = position["target_price"] * (1 - slippage)
            elif position["bars_held"] >= position["max_hold"]:
                exit_reason = "time_exit"; exit_price = closes[i]
            if exit_reason is not None:
                pnl_pct = (exit_price / position["entry_price"] - 1) * 100 - commission * 100
                trades.append({"pnl_pct": pnl_pct, "exit_reason": exit_reason})
                position = None; pending_signal = False
    return trades

def compute_metrics(trades):
    if not trades: return {"trades":0,"total_sum":0,"sharpe":0,"max_dd":0,"win_rate":0,"pf":0}
    pnls = [t["pnl_pct"] for t in trades]; total_sum = sum(pnls)
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    win_rate=len(wins)/len(pnls)*100
    sharpe=np.mean(pnls)/np.std(pnls)*np.sqrt(len(pnls)) if len(pnls)>1 and np.std(pnls)>0 else 0
    gp=sum(wins) if wins else 0; gl=abs(sum(losses)) if losses else 1
    pf=gp/gl if gl>0 else float('inf')
    eq=[10000]
    for p in pnls: eq.append(eq[-1]*(1+p/100))
    eq=np.array(eq); dd=(eq-np.maximum.accumulate(eq))/np.maximum.accumulate(eq)*100
    compound=1.0
    for p in pnls: compound*=(1+p/100)
    return {"trades":len(trades),"total_sum":total_sum,"sharpe":sharpe,
            "max_dd":dd.min(),"win_rate":win_rate,"pf":pf,"compound_return":(compound-1)*100}

def main():
    print("="*60)
    print("SPRING — EXIT OPT: EMA50>EMA200 vs SMA200")
    print("="*60)

    store = OHLCVStore(); df = store.load("okx", "BTC/USDT", "1h")
    df["sma200"] = sma(df["close"], 200)
    df["ema50"] = ema(df["close"], 50); df["ema200"] = ema(df["close"], 200)
    bb = bollinger_bands(df, 20, 2.0); df["bb_pct_b"] = bb["pct_b"]

    spring_sig = spring_signal(df)
    bb_zone = (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)

    sig_ema = spring_sig & bb_zone & (df["ema50"] > df["ema200"])
    sig_sma = spring_sig & bb_zone & (df["close"] > df["sma200"])

    print(f"\n  EMA50>EMA200 signals: {sig_ema.sum()}")
    print(f"  SMA200 signals:       {sig_sma.sum()}")

    # Grid: EMA50>EMA200
    stops = [2.5, 3.0, 3.5]; targets = [2.0, 2.5, 3.0]; holds = [20, 24, 32]
    
    print(f"\n  EMA50>EMA200 EXIT SWEEP:")
    print(f"  {'Stop':>6s} {'Target':>7s} {'Hold':>5s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print(f"  {'-'*72}")
    
    best_ema = None; best_ema_sharpe = -999
    for stop in stops:
        for target in targets:
            for hold in holds:
                trades = regime_backtest(df, sig_ema, stop_pct=stop, target_pct=target, max_hold=hold)
                m = compute_metrics(trades)
                if m["sharpe"] > best_ema_sharpe:
                    best_ema_sharpe = m["sharpe"]; best_ema = (m, stop, target, hold)
                if m["sharpe"] > 1.0:
                    print(f"  {stop:4.1f}%  {target:5.1f}%   {hold:3d}h   {m['trades']:5d}  {m['total_sum']:+8.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['pf']:5.2f}")

    print(f"\n  Best EMA: stop={best_ema[1]}%, target={best_ema[2]}%, hold={best_ema[3]}h → Sharpe={best_ema_sharpe:+.2f}")

    # Grid: SMA200 baseline
    print(f"\n  SMA200 EXIT SWEEP:")
    print(f"  {'Stop':>6s} {'Target':>7s} {'Hold':>5s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print(f"  {'-'*72}")
    
    best_sma = None; best_sma_sharpe = -999
    for stop in stops:
        for target in targets:
            for hold in holds:
                trades = regime_backtest(df, sig_sma, stop_pct=stop, target_pct=target, max_hold=hold)
                m = compute_metrics(trades)
                if m["sharpe"] > best_sma_sharpe:
                    best_sma_sharpe = m["sharpe"]; best_sma = (m, stop, target, hold)
                if m["sharpe"] > 1.0:
                    print(f"  {stop:4.1f}%  {target:5.1f}%   {hold:3d}h   {m['trades']:5d}  {m['total_sum']:+8.1f}%  {m['sharpe']:+6.2f}  {m['max_dd']:+6.1f}%  {m['win_rate']:5.1f}% {m['pf']:5.2f}")

    print(f"\n  Best SMA: stop={best_sma[1]}%, target={best_sma[2]}%, hold={best_sma[3]}h → Sharpe={best_sma_sharpe:+.2f}")

    # Comparison
    print(f"\n{'='*60}")
    print(f"COMPARISON: Best EMA vs Best SMA")
    print(f"{'='*60}")
    print(f"  {'Metric':20s} {'EMA50>EMA200':>14s} {'SMA200':>14s}")
    print(f"  {'-'*50}")
    labels = [("Trades","trades"),("Sharpe","sharpe"),("Sum %","total_sum"),
              ("MaxDD %","max_dd"),("Win Rate %","win_rate"),("PF","pf"),
              ("Cmpd Return %","compound_return")]
    for label, key in labels:
        v_ema = best_ema[0][key]; v_sma = best_sma[0][key]
        if isinstance(v_ema, float):
            print(f"  {label:20s} {v_ema:>+13.2f} {v_sma:>+13.2f}")
        else:
            print(f"  {label:20s} {v_ema:>14d} {v_sma:>14d}")

    print("\n"+"="*60)
    print("DONE")
    print("="*60)

if __name__ == "__main__":
    main()
