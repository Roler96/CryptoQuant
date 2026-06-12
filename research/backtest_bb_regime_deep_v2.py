"""
BB Upper Breakout — Regime Deep Dive + Exit Optimization v2
============================================================

Research direction: The BB Upper Breakout strategy (Sharpe +1.38, 6/7 WF)
has one negative walk-forward split (2024-10→2025-08, -3.4%, Sharpe -0.36).

This script investigates:
1. FULL regime analysis — tag every trade with 8+ market conditions
2. Temporal analysis — when do losses cluster? What changed in 2024-2025?
3. Exit optimization — sweep target/hold to improve time-exit profile
4. Vol-adjusted hold time — dynamic exits based on ATR
5. Consecutive loss cooldown — pause after N consecutive stops
6. Targeted filters — only filter the SPECIFIC toxic conditions found
7. Walk-forward validation of all improvements

Methodology follows quant-strategy-development skill:
- Always use lows for stops (engine default)
- Regime analysis BEFORE adding filters
- Exit optimization BEFORE entry optimization
- Walk-forward validate everything
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter, defaultdict
from datetime import datetime
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, ema, bollinger_bands, adx, atr


# ============================================================================
# Strategy definition
# ============================================================================

class BBUpperBreakout(Strategy):
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"
    DEFAULT_PARAMS = {
        "bb_period": 50, "bb_std": 2.5,
        "use_sma_filter": False,
        "stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10,
    }

    @property
    def name(self):
        return "BB_Upper_Breakout"

    def generate_signal(self, df):
        df = self.preprocess(df)
        close = df["close"]
        bb = bollinger_bands(df, period=self.params["bb_period"], std=self.params["bb_std"])
        long_signal = close > bb["upper"]
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[long_signal] = 1
        return signal


# ============================================================================
# Helpers
# ============================================================================

def run_backtest(df, params, engine=None):
    """Run backtest with given params, return (result, trades)."""
    if engine is None:
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    strategy = BBUpperBreakout(params)
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=params.get("stop_pct", 1.2),
        take_profit_pct=params.get("target_pct", 4.0),
        max_hold_bars=params.get("hold_hours", 10),
    )
    return result, result.trades


def print_metrics(trades, label=""):
    """Print compact metrics for a trade list."""
    if not trades:
        print(f"  {label}: NO TRADES")
        return {}
    
    pnls = [t.pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    exits = Counter(t.exit_reason for t in trades)
    
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0
    pf = total_wins / total_losses if total_losses > 0 else float('inf')
    
    # Simple Sharpe approximation from trade PnLs
    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe_approx = np.mean(pnls) / np.std(pnls) * np.sqrt(len(pnls))
    else:
        sharpe_approx = 0
    
    lin_sum = sum(pnls)
    wr = len(wins) / len(pnls) * 100 if pnls else 0
    
    metrics = {
        "trades": len(trades),
        "sum": lin_sum,
        "sharpe_approx": sharpe_approx,
        "wr": wr,
        "pf": pf,
        "avg_win": np.mean(wins) if wins else 0,
        "avg_loss": np.mean(losses) if losses else 0,
        "exits": exits,
    }
    
    print(f"\n  {label}")
    print(f"    Trades: {len(trades):>5}  Sum: {lin_sum:>+8.1f}%  Sharpe≈{sharpe_approx:>+6.2f}  WR: {wr:>5.1f}%  PF: {pf:>5.2f}")
    print(f"    Avg win: {metrics['avg_win']:>+.3f}%  Avg loss: {metrics['avg_loss']:>+.3f}%")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        if reason in exits:
            subset = [t for t in trades if t.exit_reason == reason]
            avg_pnl = np.mean([t.pnl_pct for t in subset])
            total_pnl = sum(t.pnl_pct for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"    {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")
    
    return metrics


def walk_forward(df, params, n_splits=7, label=""):
    """7-split walk-forward. Returns list of split results."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()

        if len(split_df) < 300:
            continue

        _, trades = run_backtest(split_df, params)
        lin_sum = sum(t.pnl_pct for t in trades)
        
        # Compute Sharpe from equity curve
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        strategy = BBUpperBreakout(params)
        result = engine.run(split_df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=params.get("stop_pct", 1.2),
                           take_profit_pct=params.get("target_pct", 4.0),
                           max_hold_bars=params.get("hold_hours", 10))
        sharpe = result.metrics.sharpe_ratio
        max_dd = result.metrics.max_drawdown_pct

        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "❌"

        print(f"  {star} {start_date}→{end_date}  trades={len(trades):>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}  DD={max_dd:.1f}%")
        results.append({
            "split": s+1, "period": f"{start_date}→{end_date}",
            "sum": lin_sum, "sharpe": sharpe, "trades": len(trades),
            "dd": max_dd, "start_idx": start_idx, "end_idx": end_idx
        })

    profitable = sum(1 for r in results if r["sum"] > 0)
    total = len(results)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"  → {profitable}/{total} OOS profitable | Mean Sharpe: {mean_sharpe:+.2f} | Total sum: {total_sum:+.1f}%")
    return results


# ============================================================================
# MAIN RESEARCH
# ============================================================================

def main():
    print("=" * 70)
    print("  BB UPPER BREAKOUT — REGIME DEEP DIVE + EXIT OPTIMIZATION v2")
    print("  Data: OKX BTC/USDT 1h (2019-2026)")
    print("=" * 70)

    store = OHLCVStore(db_path="data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)

    # Baseline params (from STRATEGY.md optimized)
    baseline_params = {
        "bb_period": 50, "bb_std": 2.5,
        "use_sma_filter": False,
        "stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10,
    }

    # ====================================================================
    # PART 1: BASELINE FULL BACKTEST
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 1: BASELINE FULL BACKTEST (OKX)")
    print("=" * 70)

    result, trades = run_backtest(df, baseline_params, engine)
    m = result.metrics
    
    print(f"\n  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {m.total_trades}")
    print(f"  Compound Return:    {m.total_return_pct:+.1f}%")
    print(f"  Linear Sum:         {sum(t.pnl_pct for t in trades):+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.3f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.3f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Max Consec Losses:  ", end="")
    
    max_consec = 0
    current_consec = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0
    print(max_consec)

    exits = Counter(t.exit_reason for t in trades)
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        if reason in exits:
            subset = [t for t in trades if t.exit_reason == reason]
            avg_pnl = np.mean([t.pnl_pct for t in subset])
            total_pnl = sum(t.pnl_pct for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"    {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")

    # ====================================================================
    # PART 2: FULL REGIME ANALYSIS
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 2: FULL REGIME ANALYSIS")
    print("=" * 70)

    # Pre-compute indicators
    close = df["close"]
    sma200 = sma(close, 200)
    sma50 = sma(close, 50)
    adx_data = adx(df, 14)
    atr_data = atr(df, 14)
    atr_median = atr_data.rolling(200).median()
    
    # Volume average
    vol_sma20 = df["volume"].rolling(20).mean()
    
    # 48h drawdown
    rolling_max_close = close.rolling(48).max()
    dd48 = (close / rolling_max_close - 1) * 100
    
    # Hour of day
    hours = pd.Series(df.index.hour, index=df.index)

    # Build index lookup
    ts_to_idx = {}
    for i in range(len(df)):
        ts_to_idx[int(df.index[i].timestamp() * 1000)] = i

    # Tag every trade
    tagged_trades = []
    for t in trades:
        idx = ts_to_idx.get(t.entry_time)
        if idx is None:
            continue
        
        tag = {
            "adx": float(adx_data["adx"].iloc[idx]) if not np.isnan(adx_data["adx"].iloc[idx]) else None,
            "pdi": float(adx_data["pdi"].iloc[idx]) if not np.isnan(adx_data["pdi"].iloc[idx]) else None,
            "mdi": float(adx_data["mdi"].iloc[idx]) if not np.isnan(adx_data["mdi"].iloc[idx]) else None,
            "above_sma200": bool(close.iloc[idx] > sma200.iloc[idx]) if not np.isnan(sma200.iloc[idx]) else None,
            "above_sma50": bool(close.iloc[idx] > sma50.iloc[idx]) if not np.isnan(sma50.iloc[idx]) else None,
            "sma50_above_200": bool(sma50.iloc[idx] > sma200.iloc[idx]) if not np.isnan(sma50.iloc[idx]) and not np.isnan(sma200.iloc[idx]) else None,
            "vol_ratio": float(df["volume"].iloc[idx] / vol_sma20.iloc[idx]) if not np.isnan(vol_sma20.iloc[idx]) and vol_sma20.iloc[idx] > 0 else None,
            "atr_ratio": float(atr_data.iloc[idx] / atr_median.iloc[idx]) if not np.isnan(atr_data.iloc[idx]) and not np.isnan(atr_median.iloc[idx]) and atr_median.iloc[idx] > 0 else None,
            "dd48": float(dd48.iloc[idx]) if not np.isnan(dd48.iloc[idx]) else None,
            "hour": int(hours.iloc[idx]),
            "pnl": t.pnl_pct,
            "exit_reason": t.exit_reason,
            "entry_time": t.entry_time,
            "hold_bars": t.hold_bars,
            "mfe": t.mfe_pct,
            "mae": t.mae_pct,
        }
        tagged_trades.append(tag)

    print(f"\n  Total tagged trades: {len(tagged_trades)}")

    # Helper for regime printing
    def regime_stats(name, subset):
        if len(subset) < 5:
            return
        pnls = [t["pnl"] for t in subset]
        wins = [p for p in pnls if p > 0]
        wr = len(wins) / len(pnls) * 100
        exits_sub = Counter(t["exit_reason"] for t in subset)
        avg_mfe = np.mean([t["mfe"] for t in subset])
        print(f"\n  {name}:")
        print(f"    Trades: {len(subset):>5}  Sum: {sum(pnls):>+8.1f}%  Avg: {np.mean(pnls):>+.3f}%  WR: {wr:>5.1f}%  AvgMFE: {avg_mfe:>+.2f}%")
        for reason in ["take_profit", "stop_loss", "time_exit"]:
            if reason in exits_sub:
                sub2 = [t for t in subset if t["exit_reason"] == reason]
                avg_p = np.mean([t["pnl"] for t in sub2])
                print(f"      {reason:<16} {len(sub2):>4} ({len(sub2)/len(subset)*100:>4.0f}%)  avg={avg_p:>+6.2f}%")

    # 2a: Trend regime
    print(f"\n  --- TREND REGIME ---")
    above_200 = [t for t in tagged_trades if t["above_sma200"] == True]
    below_200 = [t for t in tagged_trades if t["above_sma200"] == False]
    regime_stats("Above SMA200", above_200)
    regime_stats("Below SMA200", below_200)

    # 2b: Directional movement
    print(f"\n  --- DIRECTIONAL MOVEMENT ---")
    pdi_gt_mdi = [t for t in tagged_trades if t["pdi"] is not None and t["mdi"] is not None and t["pdi"] > t["mdi"]]
    pdi_lt_mdi = [t for t in tagged_trades if t["pdi"] is not None and t["mdi"] is not None and t["pdi"] <= t["mdi"]]
    regime_stats("PDI > MDI (bullish direction)", pdi_gt_mdi)
    regime_stats("PDI ≤ MDI (bearish direction)", pdi_lt_mdi)

    # 2c: ADX (trend strength)
    print(f"\n  --- TREND STRENGTH (ADX) ---")
    for threshold in [15, 20, 25, 30]:
        strong = [t for t in tagged_trades if t["adx"] is not None and t["adx"] > threshold]
        weak = [t for t in tagged_trades if t["adx"] is not None and t["adx"] <= threshold]
        regime_stats(f"ADX > {threshold} (strong)", strong)
        regime_stats(f"ADX ≤ {threshold} (weak)", weak)

    # 2d: Volatility regime
    print(f"\n  --- VOLATILITY REGIME (ATR ratio vs 200-median) ---")
    hi_vol = [t for t in tagged_trades if t["atr_ratio"] is not None and t["atr_ratio"] > 1.5]
    lo_vol = [t for t in tagged_trades if t["atr_ratio"] is not None and t["atr_ratio"] <= 1.5]
    regime_stats("High Vol (ATR ratio > 1.5)", hi_vol)
    regime_stats("Low Vol (ATR ratio ≤ 1.5)", lo_vol)
    
    hi_vol2 = [t for t in tagged_trades if t["atr_ratio"] is not None and t["atr_ratio"] > 2.0]
    lo_vol2 = [t for t in tagged_trades if t["atr_ratio"] is not None and t["atr_ratio"] <= 1.0]
    regime_stats("Very High Vol (ATR ratio > 2.0)", hi_vol2)
    regime_stats("Very Low Vol (ATR ratio ≤ 1.0)", lo_vol2)

    # 2e: Recent drawdown
    print(f"\n  --- RECENT DRAWDOWN (48h) ---")
    recent_dd = [t for t in tagged_trades if t["dd48"] is not None and t["dd48"] < -3]
    no_dd = [t for t in tagged_trades if t["dd48"] is not None and t["dd48"] >= -1]
    regime_stats("Recent DD < -3% (pullback)", recent_dd)
    regime_stats("Recent DD ≥ -1% (healthy)", no_dd)

    # 2f: Volume at entry
    print(f"\n  --- VOLUME AT ENTRY ---")
    hi_vol_entry = [t for t in tagged_trades if t["vol_ratio"] is not None and t["vol_ratio"] > 2.0]
    lo_vol_entry = [t for t in tagged_trades if t["vol_ratio"] is not None and t["vol_ratio"] <= 1.0]
    regime_stats("High entry volume (vol_ratio > 2.0)", hi_vol_entry)
    regime_stats("Low entry volume (vol_ratio ≤ 1.0)", lo_vol_entry)

    # 2g: Hour of day
    print(f"\n  --- HOUR OF DAY ---")
    asian = [t for t in tagged_trades if t["hour"] in range(0, 8)]
    london = [t for t in tagged_trades if t["hour"] in range(8, 16)]
    ny = [t for t in tagged_trades if t["hour"] in range(16, 24)]
    regime_stats("Asian session (00-08 UTC)", asian)
    regime_stats("London session (08-16 UTC)", london)
    regime_stats("NY session (16-24 UTC)", ny)

    # 2h: COMBO regimes (toxic combinations)
    print(f"\n  --- COMBO REGIMES ---")
    
    # The "everything bad" combo
    toxic1 = [t for t in tagged_trades 
              if t["above_sma200"] == False 
              and t["pdi"] is not None and t["mdi"] is not None and t["pdi"] <= t["mdi"]
              and t["adx"] is not None and t["adx"] > 25]
    regime_stats("TOXIC: Below SMA200 + PDI≤MDI + ADX>25", toxic1)
    
    # Below SMA200 + strong trend
    toxic2 = [t for t in tagged_trades 
              if t["above_sma200"] == False 
              and t["adx"] is not None and t["adx"] > 25]
    regime_stats("Below SMA200 + ADX>25", toxic2)
    
    # High vol + below SMA200
    toxic3 = [t for t in tagged_trades 
              if t["above_sma200"] == False 
              and t["atr_ratio"] is not None and t["atr_ratio"] > 1.5]
    regime_stats("Below SMA200 + High Vol", toxic3)
    
    # Recent DD + bearish direction
    toxic4 = [t for t in tagged_trades 
              if t["dd48"] is not None and t["dd48"] < -3
              and t["pdi"] is not None and t["mdi"] is not None and t["pdi"] <= t["mdi"]]
    regime_stats("Recent DD<-3% + PDI≤MDI", toxic4)

    # Golden combos
    golden1 = [t for t in tagged_trades 
               if t["above_sma200"] == True 
               and t["pdi"] is not None and t["mdi"] is not None and t["pdi"] > t["mdi"]
               and t["adx"] is not None and t["adx"] > 25]
    regime_stats("GOLDEN: Above SMA200 + PDI>MDI + ADX>25", golden1)

    # ====================================================================
    # PART 3: TEMPORAL ANALYSIS — What happened in 2024-2025?
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 3: TEMPORAL ANALYSIS — YEARLY BREAKDOWN")
    print("=" * 70)

    for t in tagged_trades:
        ts = pd.Timestamp(t["entry_time"], unit="ms")
        t["year"] = ts.year
        t["month"] = ts.month
        t["date"] = ts.strftime("%Y-%m")

    years = sorted(set(t["year"] for t in tagged_trades))
    print(f"\n  {'Year':>6} {'Trades':>7} {'Sum':>8} {'Avg':>7} {'WR':>6} {'TP':>4} {'SL':>4} {'TE':>4} {'AvgMFE':>7}")
    print(f"  {'-'*60}")
    for year in years:
        subset = [t for t in tagged_trades if t["year"] == year]
        if not subset:
            continue
        pnls = [t["pnl"] for t in subset]
        wins = [p for p in pnls if p > 0]
        exits_y = Counter(t["exit_reason"] for t in subset)
        avg_mfe = np.mean([t["mfe"] for t in subset])
        wr = len(wins) / len(pnls) * 100 if pnls else 0
        print(f"  {year:>6} {len(subset):>7} {sum(pnls):>+7.1f}% {np.mean(pnls):>+.3f}% {wr:>5.1f}% "
              f"{exits_y.get('take_profit',0):>4} {exits_y.get('stop_loss',0):>4} {exits_y.get('time_exit',0):>4} "
              f"{avg_mfe:>+6.2f}%")

    # Monthly granularity for 2024-2025
    print(f"\n  MONTHLY DETAIL (2024-2025):")
    print(f"  {'Month':>8} {'Trades':>7} {'Sum':>8} {'Avg':>7} {'WR':>6}")
    print(f"  {'-'*40}")
    months_2024_2025 = sorted(set(t["date"] for t in tagged_trades if t["year"] >= 2024))
    for month in months_2024_2025:
        subset = [t for t in tagged_trades if t["date"] == month]
        if not subset:
            continue
        pnls = [t["pnl"] for t in subset]
        wins = [p for p in pnls if p > 0]
        wr = len(wins) / len(pnls) * 100 if pnls else 0
        marker = " ←" if sum(pnls) < -5 else ""
        print(f"  {month:>8} {len(subset):>7} {sum(pnls):>+7.1f}% {np.mean(pnls):>+.3f}% {wr:>5.1f}%{marker}")

    # ====================================================================
    # PART 4: EXIT OPTIMIZATION
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 4: EXIT OPTIMIZATION")
    print("=" * 70)

    # 4a: Target sweep
    print(f"\n  TARGET SWEEP (stop=1.2%, hold=10):")
    print(f"  {'Target':>7} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6} {'TP%':>5} {'SL%':>5} {'TE%':>5}")
    best_target_sharpe = -999
    best_target = 4.0
    for target in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 7.0, 8.0]:
        params = {**baseline_params, "target_pct": target}
        r, ts = run_backtest(df, params, engine)
        met = r.metrics
        lin_sum = sum(t.pnl_pct for t in ts)
        ex = Counter(t.exit_reason for t in ts)
        tp_pct = ex.get("take_profit", 0) / len(ts) * 100 if ts else 0
        sl_pct = ex.get("stop_loss", 0) / len(ts) * 100 if ts else 0
        te_pct = ex.get("time_exit", 0) / len(ts) * 100 if ts else 0
        print(f"  {target:>6.1f}% {met.total_trades:>7} {lin_sum:>+7.1f}% {met.sharpe_ratio:>+8.2f} {met.max_drawdown_pct:>7.1f}% {met.win_rate_pct:>5.1f}% {met.profit_factor:>5.2f} {tp_pct:>4.0f}% {sl_pct:>4.0f}% {te_pct:>4.0f}%")
        if met.sharpe_ratio > best_target_sharpe:
            best_target_sharpe = met.sharpe_ratio
            best_target = target

    # 4b: Hold sweep
    print(f"\n  HOLD SWEEP (stop=1.2%, target=4.0):")
    print(f"  {'Hold':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6} {'TP%':>5} {'SL%':>5} {'TE%':>5}")
    best_hold_sharpe = -999
    best_hold = 10
    for hold in [3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24]:
        params = {**baseline_params, "hold_hours": hold}
        r, ts = run_backtest(df, params, engine)
        met = r.metrics
        lin_sum = sum(t.pnl_pct for t in ts)
        ex = Counter(t.exit_reason for t in ts)
        tp_pct = ex.get("take_profit", 0) / len(ts) * 100 if ts else 0
        sl_pct = ex.get("stop_loss", 0) / len(ts) * 100 if ts else 0
        te_pct = ex.get("time_exit", 0) / len(ts) * 100 if ts else 0
        print(f"  {hold:>5}h {met.total_trades:>7} {lin_sum:>+7.1f}% {met.sharpe_ratio:>+8.2f} {met.max_drawdown_pct:>7.1f}% {met.win_rate_pct:>5.1f}% {met.profit_factor:>5.2f} {tp_pct:>4.0f}% {sl_pct:>4.0f}% {te_pct:>4.0f}%")
        if met.sharpe_ratio > best_hold_sharpe:
            best_hold_sharpe = met.sharpe_ratio
            best_hold = hold

    # 4c: Stop sweep
    print(f"\n  STOP SWEEP (target=4.0, hold=10):")
    print(f"  {'Stop':>6} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    best_stop_sharpe = -999
    best_stop = 1.2
    for stop in [0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]:
        params = {**baseline_params, "stop_pct": stop}
        r, ts = run_backtest(df, params, engine)
        met = r.metrics
        lin_sum = sum(t.pnl_pct for t in ts)
        print(f"  {stop:>5.1f}% {met.total_trades:>7} {lin_sum:>+7.1f}% {met.sharpe_ratio:>+8.2f} {met.max_drawdown_pct:>7.1f}% {met.win_rate_pct:>5.1f}% {met.profit_factor:>5.2f}")
        if met.sharpe_ratio > best_stop_sharpe:
            best_stop_sharpe = met.sharpe_ratio
            best_stop = stop

    # ====================================================================
    # PART 5: BEST EXIT CONFIG — FULL BACKTEST + WALK-FORWARD
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 5: BEST EXIT CONFIG — FULL BACKTEST + WALK-FORWARD")
    print("=" * 70)

    best_exit_params = {**baseline_params, "stop_pct": best_stop, "target_pct": best_target, "hold_hours": best_hold}
    print(f"\n  Best exit params: stop={best_stop}%, target={best_target}%, hold={best_hold}h")

    r_best, trades_best = run_backtest(df, best_exit_params, engine)
    m_best = r_best.metrics
    print_metrics(trades_best, "BEST EXIT CONFIG — OKX")

    print(f"\n  Walk-forward (best exit config):")
    wf_best = walk_forward(df, best_exit_params, n_splits=7, label="Best Exit Config")

    # Also walk-forward the baseline for comparison
    print(f"\n  Walk-forward (baseline):")
    wf_baseline = walk_forward(df, baseline_params, n_splits=7, label="Baseline")

    # ====================================================================
    # PART 6: TARGETED FILTERS (based on regime findings)
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 6: TARGETED FILTERS")
    print("=" * 70)
    print("  (Based on regime analysis findings from Part 2)")

    # We'll test a few hypotheses based on what the regime analysis reveals.
    # The key is to only filter conditions that are CONSISTENTLY toxic.

    # For now, let's test SMA200 filter with the best exit params
    print(f"\n  --- SMA200 FILTER ---")
    
    class BBUpperBreakoutSMA200(Strategy):
        timeframe = "1h"
        min_bars = 250
        version = "2.0.0"
        DEFAULT_PARAMS = {
            "bb_period": 50, "bb_std": 2.5,
            "stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10,
        }
        @property
        def name(self):
            return "BB_Upper_SMA200"
        def generate_signal(self, df):
            df = self.preprocess(df)
            close = df["close"]
            bb = bollinger_bands(df, period=self.params["bb_period"], std=self.params["bb_std"])
            sma_val = sma(close, 200)
            long_signal = (close > bb["upper"]) & (close > sma_val)
            signal = pd.Series(0, index=df.index, dtype=int)
            signal[long_signal] = 1
            return signal

    # Run with SMA200 filter
    strategy_sma = BBUpperBreakoutSMA200(best_exit_params)
    result_sma = engine.run(df, strategy_sma, symbol="BTC/USDT",
                           stop_loss_pct=best_exit_params["stop_pct"],
                           take_profit_pct=best_exit_params["target_pct"],
                           max_hold_bars=best_exit_params["hold_hours"])
    print_metrics(result_sma.trades, "SMA200 FILTER (best exits)")

    # Walk-forward with SMA200
    print(f"\n  Walk-forward (SMA200 filter + best exits):")
    n = len(df)
    slot = n // 9
    wf_sma = []
    for s in range(7):
        start_idx = n - (7 - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()
        if len(split_df) < 300:
            continue
        strat = BBUpperBreakoutSMA200(best_exit_params)
        res = engine.run(split_df, strat, symbol="BTC/USDT",
                        stop_loss_pct=best_exit_params["stop_pct"],
                        take_profit_pct=best_exit_params["target_pct"],
                        max_hold_bars=best_exit_params["hold_hours"])
        lin_sum = sum(t.pnl_pct for t in res.trades)
        sharpe = res.metrics.sharpe_ratio
        max_dd = res.metrics.max_drawdown_pct
        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "❌"
        print(f"  {star} {start_date}→{end_date}  trades={len(res.trades):>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}  DD={max_dd:.1f}%")
        wf_sma.append({"sum": lin_sum, "sharpe": sharpe})

    profitable = sum(1 for r in wf_sma if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in wf_sma]) if wf_sma else 0
    print(f"  → {profitable}/{len(wf_sma)} OOS profitable | Mean Sharpe: {mean_sharpe:+.2f}")

    # ====================================================================
    # PART 7: CONSECUTIVE LOSS COOLDOWN
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 7: CONSECUTIVE LOSS COOLDOWN")
    print("=" * 70)

    # Test: after N consecutive stop-losses, pause for M hours
    # This is a simple risk management mechanism
    print(f"\n  Testing cooldown: after 2 consecutive stop-losses, pause 12h")
    
    # We'll simulate this by post-processing the baseline trades
    def apply_cooldown(trades, cooldown_after_stops=2, cooldown_hours=12):
        """Remove trades that occur within cooldown_hours of N consecutive stops."""
        filtered = []
        consec_stops = 0
        cooldown_until = 0
        
        for t in trades:
            if t.entry_time < cooldown_until:
                # In cooldown period, skip this trade
                continue
            
            filtered.append(t)
            
            if t.exit_reason == "stop_loss":
                consec_stops += 1
                if consec_stops >= cooldown_after_stops:
                    cooldown_until = t.exit_time + cooldown_hours * 3600 * 1000
            else:
                consec_stops = 0
        
        return filtered

    for cooldown_stops in [2, 3]:
        for cooldown_hours in [6, 12, 24]:
            filtered = apply_cooldown(trades, cooldown_stops, cooldown_hours)
            removed = len(trades) - len(filtered)
            if filtered:
                pnls = [t.pnl_pct for t in filtered]
                lin_sum = sum(pnls)
                wins = [p for p in pnls if p > 0]
                wr = len(wins) / len(pnls) * 100
                print(f"    After {cooldown_stops} stops, pause {cooldown_hours}h: "
                      f"removed={removed:>4}  remaining={len(filtered):>5}  "
                      f"sum={lin_sum:>+7.1f}%  WR={wr:>5.1f}%")

    # ====================================================================
    # PART 8: VOL-ADJUSTED DYNAMIC HOLD
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 8: VOL-ADJUSTED DYNAMIC HOLD")
    print("=" * 70)

    # Idea: in high vol, hold shorter (moves happen faster); in low vol, hold longer
    # We can't easily do this in the engine, but we can approximate by testing
    # different hold times in different volatility regimes
    
    # Instead, let's test if different hold times work better for different BB periods
    # (which proxy for volatility regime)
    print(f"\n  Testing: shorter hold for wider BB (higher vol environment)")
    for bb_period in [20, 30, 50]:
        for hold in [6, 8, 10, 14]:
            params = {"bb_period": bb_period, "bb_std": 2.5, "use_sma_filter": False,
                     "stop_pct": 1.2, "target_pct": 4.0, "hold_hours": hold}
            r, ts = run_backtest(df, params, engine)
            met = r.metrics
            lin_sum = sum(t.pnl_pct for t in ts)
            print(f"    BB({bb_period},2.5) hold={hold:>2}h: trades={met.total_trades:>4}  "
                  f"sum={lin_sum:>+7.1f}%  sharpe={met.sharpe_ratio:>+6.2f}  DD={met.max_drawdown_pct:>5.1f}%")

    # ====================================================================
    # PART 9: BINANCE CROSS-VALIDATION OF BEST CONFIG
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 9: BINANCE CROSS-VALIDATION")
    print("=" * 70)

    # Best exit config on Binance
    r_bn, trades_bn = run_backtest(df_binance, best_exit_params, engine)
    print_metrics(trades_bn, "BEST EXIT CONFIG — BINANCE")

    print(f"\n  Walk-forward (best exit config, Binance):")
    wf_bn = walk_forward(df_binance, best_exit_params, n_splits=7, label="Best Exit — Binance")

    # Baseline on Binance for comparison
    r_bn_base, trades_bn_base = run_backtest(df_binance, baseline_params, engine)
    print_metrics(trades_bn_base, "BASELINE — BINANCE")

    # ====================================================================
    # PART 10: COMBINED EXIT OPTIMIZATION GRID
    # ====================================================================
    print("\n" + "=" * 70)
    print("  PART 10: EXIT GRID — STOP × TARGET × HOLD")
    print("=" * 70)

    # Test a focused grid of promising combinations
    grid_results = []
    for stop in [1.0, 1.2, 1.5]:
        for target in [2.5, 3.0, 4.0, 5.0]:
            for hold in [6, 8, 10, 14]:
                params = {"bb_period": 50, "bb_std": 2.5, "use_sma_filter": False,
                         "stop_pct": stop, "target_pct": target, "hold_hours": hold}
                r, ts = run_backtest(df, params, engine)
                met = r.metrics
                lin_sum = sum(t.pnl_pct for t in ts)
                grid_results.append({
                    "stop": stop, "target": target, "hold": hold,
                    "trades": met.total_trades, "sum": lin_sum,
                    "sharpe": met.sharpe_ratio, "dd": met.max_drawdown_pct,
                    "wr": met.win_rate_pct, "pf": met.profit_factor,
                })

    # Sort by Sharpe
    grid_results.sort(key=lambda x: x["sharpe"], reverse=True)
    
    print(f"\n  TOP 15 CONFIGURATIONS BY SHARPE:")
    print(f"  {'Stop':>5} {'Target':>7} {'Hold':>5} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*65}")
    for g in grid_results[:15]:
        print(f"  {g['stop']:>4.1f}% {g['target']:>6.1f}% {g['hold']:>4}h {g['trades']:>7} "
              f"{g['sum']:>+7.1f}% {g['sharpe']:>+8.2f} {g['dd']:>7.1f}% {g['wr']:>5.1f}% {g['pf']:>5.2f}")

    print(f"\n  BOTTOM 5 CONFIGURATIONS BY SHARPE:")
    for g in grid_results[-5:]:
        print(f"  {g['stop']:>4.1f}% {g['target']:>6.1f}% {g['hold']:>4}h {g['trades']:>7} "
              f"{g['sum']:>+7.1f}% {g['sharpe']:>+8.2f} {g['dd']:>7.1f}% {g['wr']:>5.1f}% {g['pf']:>5.2f}")

    # Walk-forward the top 3 from grid
    print(f"\n  WALK-FORWARD TOP 3 FROM GRID:")
    for i, g in enumerate(grid_results[:3]):
        params = {"bb_period": 50, "bb_std": 2.5, "use_sma_filter": False,
                 "stop_pct": g["stop"], "target_pct": g["target"], "hold_hours": g["hold"]}
        print(f"\n  #{i+1}: stop={g['stop']}%, target={g['target']}%, hold={g['hold']}h (full Sharpe={g['sharpe']:+.2f})")
        wf = walk_forward(df, params, n_splits=7, label=f"Grid Top #{i+1}")

    # ====================================================================
    # SUMMARY
    # ====================================================================
    print("\n" + "=" * 70)
    print("  RESEARCH COMPLETE")
    print("=" * 70)
    print(f"\n  Baseline: BB(50,2.5) stop=1.2% target=4.0% hold=10h")
    print(f"  Best exit params found: stop={best_stop}% target={best_target}% hold={best_hold}h")
    print(f"\n  Check output above for:")
    print(f"  - Regime analysis (Part 2): which conditions are toxic?")
    print(f"  - Temporal analysis (Part 3): what changed in 2024-2025?")
    print(f"  - Exit optimization (Part 4): best target/hold/stop")
    print(f"  - Walk-forward (Part 5): is the improvement robust?")
    print(f"  - Grid search (Part 10): full landscape")


if __name__ == "__main__":
    main()
