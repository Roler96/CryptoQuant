"""
Spring Reversal — EMA50>EMA200 Walk-Forward + Binance Validation
=================================================================
Final validation of the best configuration:
  Filter: BB %B 0.2-0.6 + EMA50 > EMA200
  Exits:  stop=3.0%, target=3.0%, hold=32h
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
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

def regime_backtest(df, signals, stop_pct=3.0, target_pct=3.0,
                    max_hold=32, commission=0.0005, slippage=0.0005):
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
                mfe_pct = (position["high_since_entry"] / position["entry_price"] - 1) * 100
                mae_pct = (position["low_since_entry"] / position["entry_price"] - 1) * 100
                trades.append({"pnl_pct": pnl_pct, "mfe_pct": mfe_pct, "mae_pct": mae_pct,
                               "exit_reason": exit_reason, "bars_held": position["bars_held"]})
                position = None; pending_signal = False
    return trades

def compute_metrics(trades):
    if not trades: return {}
    pnls = [t["pnl_pct"] for t in trades]; total_sum = sum(pnls)
    wins=[p for p in pnls if p>0]; losses=[p for p in pnls if p<=0]
    win_rate=len(wins)/len(pnls)*100
    avg_win=np.mean(wins) if wins else 0; avg_loss=np.mean(losses) if losses else 0
    sharpe=np.mean(pnls)/np.std(pnls)*np.sqrt(len(pnls)) if len(pnls)>1 and np.std(pnls)>0 else 0
    downside=[p for p in pnls if p<0]
    sortino=np.mean(pnls)/np.std(downside)*np.sqrt(len(pnls)) if downside and len(pnls)>1 and np.std(downside)>0 else 0
    gp=sum(wins) if wins else 0; gl=abs(sum(losses)) if losses else 1
    pf=gp/gl if gl>0 else float('inf')
    eq=[10000]
    for p in pnls: eq.append(eq[-1]*(1+p/100))
    eq=np.array(eq); dd=(eq-np.maximum.accumulate(eq))/np.maximum.accumulate(eq)*100
    compound=1.0
    for p in pnls: compound*=(1+p/100)
    compound_return=(compound-1)*100
    ec=Counter(t["exit_reason"] for t in trades)
    exit_detail={}
    for reason in ["take_profit","stop_loss","time_exit"]:
        subset=[t for t in trades if t["exit_reason"]==reason]
        if subset:
            sp=[t["pnl_pct"] for t in subset]
            exit_detail[reason]={"count":len(subset),"pct":len(subset)/len(trades)*100,
                                 "avg":np.mean(sp),"total":sum(sp)}
    max_consec=0; consec=0
    for p in pnls:
        if p<=0: consec+=1; max_consec=max(max_consec,consec)
        else: consec=0
    mfes=[t["mfe_pct"] for t in trades]; maes=[t["mae_pct"] for t in trades]
    return {"trades":len(trades),"total_sum":total_sum,"sharpe":sharpe,"sortino":sortino,
            "max_dd":dd.min(),"win_rate":win_rate,"avg_win":avg_win,"avg_loss":avg_loss,
            "pf":pf,"compound_return":compound_return,"exit_breakdown":exit_detail,
            "max_consec":max_consec,"mfes":mfes,"maes":maes,"trades_list":trades}

# ============================================================================
# MAIN
# ============================================================================

def main():
    print("="*70)
    print("SPRING REVERSAL — EMA50>EMA200 FINAL VALIDATION")
    print("="*70)

    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    print(f"\nOKX: {len(df_okx)} bars")
    print(f"Binance: {len(df_binance)} bars")

    base_params = {"stop_pct": 3.0, "target_pct": 3.0, "max_hold": 32,
                   "commission": 0.0005, "slippage": 0.0005}

    # ========================================================================
    # OKX: Full Backtest
    # ========================================================================
    df = df_okx.copy()
    df["sma200"] = sma(df["close"], 200)
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    bb = bollinger_bands(df, 20, 2.0)
    df["bb_pct_b"] = bb["pct_b"]

    spring_sig = spring_signal(df)
    bb_zone = (df["bb_pct_b"] >= 0.2) & (df["bb_pct_b"] < 0.6)

    # EMA50>EMA200 filter
    sig_ema = spring_sig & bb_zone & (df["ema50"] > df["ema200"])
    # SMA200 baseline
    sig_sma = spring_sig & bb_zone & (df["close"] > df["sma200"])

    # ========================================================================
    # OKX Full Backtest
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"FULL BACKTEST: EMA50>EMA200 + BB %B 0.2-0.6")
    print(f"{'='*55}")
    print(f"  Signal count: {sig_ema.sum()}")

    trades_ema = regime_backtest(df, sig_ema, **base_params)
    m_ema = compute_metrics(trades_ema)

    print(f"\n  Total Trades:       {m_ema['trades']}")
    print(f"  Compound Return:    {m_ema['compound_return']:+.1f}%")
    print(f"  Linear Sum:         {m_ema['total_sum']:+.1f}%")
    print(f"  Sharpe Ratio:       {m_ema['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {m_ema['sortino']:+.2f}")
    print(f"  Max Drawdown:       {m_ema['max_dd']:+.1f}%")
    print(f"  Win Rate:           {m_ema['win_rate']:.1f}%")
    print(f"  Avg Win:            {m_ema['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {m_ema['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {m_ema['pf']:.2f}")
    print(f"  Max Consec Losses:  {m_ema['max_consec']}")

    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        d = m_ema["exit_breakdown"].get(reason)
        if d:
            print(f"    {reason:15s}: {d['count']:4d} ({d['pct']:5.1f}%)  avg={d['avg']:+.2f}%  total={d['total']:+.1f}%")

    print(f"\n  MFE: mean={np.mean(m_ema['mfes']):+.2f}%  median={np.median(m_ema['mfes']):+.2f}%  max={np.max(m_ema['mfes']):+.2f}%")
    print(f"  MAE: mean={np.mean(m_ema['maes']):+.2f}%  median={np.median(m_ema['maes']):+.2f}%")
    time_ex = [t for t in trades_ema if t["exit_reason"]=="time_exit"]
    if time_ex:
        pt = sum(1 for t in time_ex if t["mfe_pct"]>0)
        print(f"  Time-exits profitable at some point: {pt}/{len(time_ex)} ({pt/len(time_ex)*100:.1f}%)")

    # ========================================================================
    # OKX: SMA200 Baseline
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"SMA200 BASELINE (for comparison)")
    print(f"{'='*55}")
    print(f"  Signal count: {sig_sma.sum()}")

    trades_sma = regime_backtest(df, sig_sma, **base_params)
    m_sma = compute_metrics(trades_sma)

    print(f"\n  Total Trades:       {m_sma['trades']}")
    print(f"  Compound Return:    {m_sma['compound_return']:+.1f}%")
    print(f"  Linear Sum:         {m_sma['total_sum']:+.1f}%")
    print(f"  Sharpe Ratio:       {m_sma['sharpe']:+.2f}")
    print(f"  Max Drawdown:       {m_sma['max_dd']:+.1f}%")
    print(f"  Win Rate:           {m_sma['win_rate']:.1f}%")
    print(f"  Profit Factor:      {m_sma['pf']:.2f}")

    # ========================================================================
    # WALK-FORWARD: EMA50>EMA200 (7 splits)
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"WALK-FORWARD: EMA50>EMA200 (7 splits)")
    print(f"{'='*55}")

    n = len(df); n_splits = 7
    slot = n // (n_splits + 2)
    wf_positive = 0; wf_sharpes = []; total_wf_sum = 0
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]; split_sig = sig_ema.iloc[start:end]
        t = regime_backtest(split_df, split_sig, **base_params)
        if t:
            p = [x["pnl_pct"] for x in t]
            ss = sum(p)
            ssh = np.mean(p)/np.std(p)*np.sqrt(len(p)) if len(p)>1 and np.std(p)>0 else 0
            eq=[10000]
            for x in p: eq.append(eq[-1]*(1+x/100))
            eq=np.array(eq); sdd=(eq-np.maximum.accumulate(eq))/np.maximum.accumulate(eq)*100
            max_dd=sdd.min()
        else:
            ss=0; ssh=0; max_dd=0
        if ss>0: wf_positive+=1
        wf_sharpes.append(ssh); total_wf_sum+=ss
        status="✅" if ss>0 else "❌"
        print(f"  Split {s+1}: {split_df.index[0].strftime('%Y-%m')}→{split_df.index[-1].strftime('%Y-%m')}  trades={len(t):3d}  sum={ss:+6.1f}%  sharpe={ssh:+6.2f}  dd={max_dd:+5.1f}%  {status}")

    print(f"\n  OOS Profitable: {wf_positive}/{n_splits} splits")
    print(f"  Mean OOS Sharpe: {np.mean(wf_sharpes):+.2f}")
    print(f"  Total OOS Sum: {total_wf_sum:+.1f}%")

    # ========================================================================
    # WALK-FORWARD: SMA200 (7 splits)
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"WALK-FORWARD: SMA200 Baseline (7 splits)")
    print(f"{'='*55}")

    wf_pos_sma = 0; wf_sh_sma = []; tot_wf_sma = 0
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]; split_sig = sig_sma.iloc[start:end]
        t = regime_backtest(split_df, split_sig, **base_params)
        if t:
            p = [x["pnl_pct"] for x in t]
            ss = sum(p)
            ssh = np.mean(p)/np.std(p)*np.sqrt(len(p)) if len(p)>1 and np.std(p)>0 else 0
            eq=[10000]
            for x in p: eq.append(eq[-1]*(1+x/100))
            eq=np.array(eq); sdd=(eq-np.maximum.accumulate(eq))/np.maximum.accumulate(eq)*100
            max_dd=sdd.min()
        else:
            ss=0; ssh=0; max_dd=0
        if ss>0: wf_pos_sma+=1
        wf_sh_sma.append(ssh); tot_wf_sma+=ss
        status="✅" if ss>0 else "❌"
        print(f"  Split {s+1}: {split_df.index[0].strftime('%Y-%m')}→{split_df.index[-1].strftime('%Y-%m')}  trades={len(t):3d}  sum={ss:+6.1f}%  sharpe={ssh:+6.2f}  dd={max_dd:+5.1f}%  {status}")

    print(f"\n  OOS Profitable: {wf_pos_sma}/{n_splits} splits")
    print(f"  Mean OOS Sharpe: {np.mean(wf_sh_sma):+.2f}")
    print(f"  Total OOS Sum: {tot_wf_sma:+.1f}%")

    # ========================================================================
    # BINANCE CROSS-VALIDATION
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"BINANCE CROSS-VALIDATION: EMA50>EMA200")
    print(f"{'='*55}")

    df_b = df_binance.copy()
    df_b["sma200"] = sma(df_b["close"], 200)
    df_b["ema50"] = ema(df_b["close"], 50)
    df_b["ema200"] = ema(df_b["close"], 200)
    bb_b = bollinger_bands(df_b, 20, 2.0)
    df_b["bb_pct_b"] = bb_b["pct_b"]

    spring_sig_b = spring_signal(df_b)
    bb_zone_b = (df_b["bb_pct_b"] >= 0.2) & (df_b["bb_pct_b"] < 0.6)
    sig_ema_b = spring_sig_b & bb_zone_b & (df_b["ema50"] > df_b["ema200"])
    sig_sma_b = spring_sig_b & bb_zone_b & (df_b["close"] > df_b["sma200"])

    print(f"  Signal count (EMA): {sig_ema_b.sum()}")
    print(f"  Signal count (SMA): {sig_sma_b.sum()}")

    trades_ema_b = regime_backtest(df_b, sig_ema_b, **base_params)
    m_ema_b = compute_metrics(trades_ema_b)

    trades_sma_b = regime_backtest(df_b, sig_sma_b, **base_params)
    m_sma_b = compute_metrics(trades_sma_b)

    print(f"\n  Cross-Exchange Comparison:")
    print(f"  {'Metric':20s} {'OKX EMA':>10s} {'OKX SMA':>10s} {'BIN EMA':>10s} {'BIN SMA':>10s}")
    print(f"  {'-'*52}")
    for label, key in [("Trades","trades"),("Sharpe","sharpe"),("Max DD %","max_dd"),
                        ("Win Rate %","win_rate"),("PF","pf"),("Sum %","total_sum")]:
        v1=m_ema[key]; v2=m_sma[key]; v3=m_ema_b[key]; v4=m_sma_b[key]
        if isinstance(v1,float):
            print(f"  {label:20s} {v1:>+10.2f} {v2:>+10.2f} {v3:>+10.2f} {v4:>+10.2f}")
        else:
            print(f"  {label:20s} {v1:>10d} {v2:>10d} {v3:>10d} {v4:>10d}")

    # ========================================================================
    # FINAL COMPARISON TABLE
    # ========================================================================
    print(f"\n{'='*55}")
    print(f"FINAL: EMA50>EMA200 vs SMA200 (OKX)")
    print(f"{'='*55}")
    print(f"\n  {'Metric':20s} {'SMA200':>12s} {'EMA50>EMA200':>15s} {'Delta':>12s}")
    print(f"  {'-'*62}")
    comparisons = [
        ("Trades", m_sma["trades"], m_ema["trades"]),
        ("Sharpe", m_sma["sharpe"], m_ema["sharpe"]),
        ("Compound Return", m_sma["compound_return"], m_ema["compound_return"]),
        ("Max Drawdown", m_sma["max_dd"], m_ema["max_dd"]),
        ("Win Rate", m_sma["win_rate"], m_ema["win_rate"]),
        ("Profit Factor", m_sma["pf"], m_ema["pf"]),
        ("WF Profitable", f"{wf_pos_sma}/7", f"{wf_positive}/7"),
        ("Mean WF Sharpe", np.mean(wf_sh_sma), np.mean(wf_sharpes)),
    ]
    for label, base, best in comparisons:
        if isinstance(base, float):
            print(f"  {label:20s} {base:>+11.2f} {best:>+14.2f} {best-base:>+11.2f}")
        else:
            print(f"  {label:20s} {str(base):>12s} {str(best):>15s}")

    print("\n" + "="*70)
    print("VALIDATION COMPLETE")
    print("="*70)

if __name__ == "__main__":
    main()
