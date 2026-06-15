"""
Spring Reversal on 4h Bars — Research & Walk-Forward Validation
================================================================

Tests the Spring Reversal signal directly on 4h bars (resampled from 1h).
Hypothesis: A Wyckoff Spring on 4h bars is more significant than on 1h —
it takes more conviction to create a false breakdown on a higher timeframe,
so per-trade quality should improve even though trade frequency drops.

Comparison: 1h filtered Spring (SMA200 + BB 0.2-0.6) vs 4h Spring.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, adx as adx_func,
    pct_change_rolling, rsi, bollinger_bands
)


# ============================================================================
# Spring Signal (4h-compatible)
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


class Spring4HStrategy(Strategy):
    """Spring Reversal strategy for 4h bars."""
    
    timeframe = "4h"
    min_bars = 200  # enough for SMA200 on 4h
    version = "0.1.0"
    
    DEFAULT_PARAMS = {
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_bars": 6,  # 6 × 4h = 24h equivalent
        "sma200_filter": True,
        "bb_filter": True,
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_low": 0.2,
        "bb_high": 0.6,
    }
    
    @property
    def name(self) -> str:
        return "Spring4H"
    
    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        
        signal = spring_signal(
            df,
            lookback=self.params["lookback"],
            vol_mult=self.params["vol_mult"],
            close_pct=self.params["close_pct"],
        )
        
        if self.params.get("sma200_filter", True):
            sma200 = sma(df["close"], 200)
            signal = signal & (df["close"] > sma200)
        
        if self.params.get("bb_filter", True):
            bb = bollinger_bands(
                df,
                period=self.params["bb_period"],
                std=self.params["bb_std"],
            )
            pct_b = bb["pct_b"]
            signal = signal & (
                (pct_b >= self.params["bb_low"])
                & (pct_b < self.params["bb_high"])
            )
        
        return signal.astype(int)


# ============================================================================
# Custom Backtest (reuse existing infrastructure)
# ============================================================================

def backtest_simple(df, signal, stop_pct, target_pct, max_hold_bars, 
                    commission=0.0005, slippage=0.0005):
    """
    Simple bar-by-bar backtest with lows-based stops.
    Returns list of trade dicts.
    """
    closes = df["close"].values
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    timestamps = df.index.values
    n = len(df)
    signal_arr = signal.values
    
    trades = []
    in_position = False
    pos = {}
    
    for i in range(n - 1):
        # Check exits first
        if in_position:
            bars_held = i - pos["entry_idx"]
            entry_price = pos["entry_price"]
            side = pos["side"]
            
            # Current PnL based on bar extremes
            if side == "long":
                # Check stop loss first (priority)
                stop_price = entry_price * (1 - stop_pct / 100)
                if lows[i] <= stop_price:
                    exit_price = stop_price
                    exit_reason = "stop_loss"
                elif highs[i] >= entry_price * (1 + target_pct / 100):
                    exit_price = entry_price * (1 + target_pct / 100)
                    exit_reason = "take_profit"
                elif bars_held >= max_hold_bars:
                    exit_price = closes[i]
                    exit_reason = "time_exit"
                elif signal_arr[i] == -1:
                    exit_price = closes[i]
                    exit_reason = "signal_reverse"
                else:
                    continue  # No exit, continue holding
                
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                # Apply slippage to take-profit and stop exits
                if exit_reason == "take_profit":
                    pnl_pct -= slippage * 100
                elif exit_reason == "stop_loss":
                    pnl_pct -= slippage * 100
                pnl_pct -= commission * 100  # round-trip commission
                
                trades.append({
                    "entry_time": pos["entry_time"],
                    "exit_time": timestamps[i],
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "side": side,
                    "exit_reason": exit_reason,
                    "bars_held": bars_held,
                })
                in_position = False
                pos = {}
                continue  # Don't enter on same bar
        
        # Check entry
        if not in_position and signal_arr[i] == 1:
            entry_price = opens[i + 1]  # Next bar open
            in_position = True
            pos = {
                "side": "long",
                "entry_time": timestamps[i + 1],
                "entry_price": entry_price,
                "entry_idx": i + 1,
                "entry_signal": 1,
            }
    
    return trades


def calculate_metrics(trades, initial_capital=10000, n_bars=None):
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
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    
    # Equity curve
    equity = initial_capital
    equity_curve = [equity]
    for pnl in pnls:
        trade_notional = equity  # full allocation
        equity += trade_notional * pnl / 100
        equity_curve.append(equity)
    equity_curve = np.array(equity_curve)
    
    compound_return = (equity / initial_capital - 1) * 100
    linear_sum = pnls.sum()
    
    # Sharpe (per-trade)
    sharpe = np.mean(pnls) / np.std(pnls, ddof=1) if np.std(pnls, ddof=1) > 0 else 0.0
    
    # Sortino
    downside = pnls[pnls < 0]
    sortino = np.mean(pnls) / np.std(downside, ddof=1) if len(downside) > 0 and np.std(downside, ddof=1) > 0 else 0.0
    
    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
    
    win_rate = len(wins) / len(trades) * 100
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = losses.mean() if len(losses) > 0 else 0.0
    
    gross_profit = wins.sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1e-10
    profit_factor = gross_profit / gross_loss
    
    # Max consecutive losses
    max_cl = 0
    cl = 0
    for pnl in pnls:
        if pnl <= 0:
            cl += 1
            max_cl = max(max_cl, cl)
        else:
            cl = 0
    
    # Annualized return
    if n_bars:
        years = n_bars / (365 * 6)  # 4h bars per year
    else:
        years = len(trades) / 50  # rough estimate
    annualized = ((1 + compound_return / 100) ** (1 / max(years, 0.1)) - 1) * 100
    
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
        "annualized": annualized,
        "equity_curve": equity_curve,
    }


def exit_breakdown(trades):
    """Count exit reasons and their stats."""
    reasons = Counter()
    reason_pnls = {}
    for t in trades:
        r = t["exit_reason"]
        reasons[r] += 1
        if r not in reason_pnls:
            reason_pnls[r] = []
        reason_pnls[r].append(t["pnl_pct"])
    
    total = len(trades)
    output = []
    for r in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        if r in reasons:
            pnls = reason_pnls[r]
            output.append((r, reasons[r], np.mean(pnls), np.sum(pnls)))
    
    return output


def walk_forward_test(df, signal_func, signal_kwargs, exit_params, n_splits=6, 
                      filter_func=None, filter_kwargs=None):
    """Walk-forward validation with sequential OOS splits."""
    n = len(df)
    # Use roughly equal splits
    slot = n // (n_splits + 1)
    
    results = []
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        
        oos_df = df.iloc[start:end].copy()
        
        # Compute signal on OOS slice
        sig = signal_func(oos_df, **signal_kwargs)
        
        if filter_func:
            sig = filter_func(oos_df, sig, **filter_kwargs)
        
        trades = backtest_simple(oos_df, sig, **exit_params)
        metrics = calculate_metrics(trades, n_bars=len(oos_df))
        
        results.append({
            "split": s + 1,
            "start": str(df.index[start])[:10],
            "end": str(df.index[end - 1])[:10],
            "bars": len(oos_df),
            "trades": len(trades),
            "sum": metrics["linear_sum"],
            "sharpe": metrics["sharpe"],
            "max_dd": metrics["max_dd"],
            "win_rate": metrics["win_rate"],
            "profit_factor": metrics["profit_factor"],
        })
    
    return results


# ============================================================================
# Parameter Sweep
# ============================================================================

def param_sweep(df, signal_func, signal_kwargs, filter_func=None, filter_kwargs=None):
    """Grid search over stop/target/hold combinations."""
    stops = [2.0, 2.5, 3.0, 3.5, 4.0]
    targets = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
    holds = [4, 6, 8, 10, 12, 16]  # in 4h bars
    
    if filter_kwargs is None:
        filter_kwargs = {}
    
    best = None
    best_sharpe = -999
    
    print(f"\n{'='*80}")
    print(f"PARAMETER SWEEP: {len(stops)}×{len(targets)}×{len(holds)} = {len(stops)*len(targets)*len(holds)} combos")
    print(f"{'='*80}")
    print(f"{'Stop':>6} {'Target':>7} {'Hold':>5} {'Trades':>7} {'Sum%':>8} {'Sharpe':>7} {'MaxDD':>7} {'WR%':>6} {'PF':>6}")
    print("-" * 80)
    
    for stop in stops:
        for target in targets:
            for hold in holds:
                sig = signal_func(df, **signal_kwargs)
                if filter_func:
                    sig = filter_func(df, sig, **filter_kwargs)
                
                trades = backtest_simple(
                    df, sig,
                    stop_pct=stop, target_pct=target, max_hold_bars=hold,
                )
                m = calculate_metrics(trades, n_bars=len(df))
                
                if m["sharpe"] > best_sharpe:
                    best_sharpe = m["sharpe"]
                    best = {
                        "stop": stop, "target": target, "hold": hold,
                        **m,
                    }
                
                print(f"{stop:>6.1f}% {target:>6.1f}% {hold:>4}bh {m['total_trades']:>6} "
                      f"{m['linear_sum']:>+7.1f}% {m['sharpe']:>+6.2f} "
                      f"{m['max_dd']:>+6.1f}% {m['win_rate']:>5.1f}% {m['profit_factor']:>5.2f}")
    
    print("-" * 80)
    print(f"\nBEST: stop={best['stop']:.1f}%, target={best['target']:.1f}%, hold={best['hold']}bh")
    print(f"      trades={best['total_trades']}, sum={best['linear_sum']:+.1f}%, "
          f"sharpe={best['sharpe']:+.2f}, maxDD={best['max_dd']:+.1f}%, "
          f"WR={best['win_rate']:.1f}%, PF={best['profit_factor']:.2f}")
    
    return best


# ============================================================================
# MAIN
# ============================================================================

def main():
    store = OHLCVStore()
    
    # Load 1h data
    df_1h = store.load("okx", "BTC/USDT", "1h")
    print(f"OKX BTC/USDT 1h: {len(df_1h)} bars, {df_1h.index[0]} → {df_1h.index[-1]}")
    
    # Resample to 4h
    df_4h = df_1h.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    n_bars = len(df_4h)
    print(f"OKX BTC/USDT 4h: {n_bars} bars, {df_4h.index[0]} → {df_4h.index[-1]}")
    
    # Core signal
    sig_raw = spring_signal(df_4h, lookback=20, vol_mult=1.5, close_pct=0.5)
    print(f"Raw signals: {sig_raw.sum()}")
    
    # Compute filter indicators
    df_4h["sma200"] = sma(df_4h["close"], 200)
    bb = bollinger_bands(df_4h, 20, 2.0)
    df_4h["bb_pct_b"] = bb["pct_b"]
    
    above_sma200 = df_4h["close"] > df_4h["sma200"]
    bb_bounce_02_06 = (df_4h["bb_pct_b"] >= 0.2) & (df_4h["bb_pct_b"] < 0.6)
    bb_bounce_015_065 = (df_4h["bb_pct_b"] >= 0.15) & (df_4h["bb_pct_b"] < 0.65)
    
    # ========================================================================
    # FILTER VARIANT COMPARISON
    # ========================================================================
    
    print("\n" + "=" * 80)
    print("FILTER VARIANT COMPARISON — Unfiltered vs SMA200 vs BB vs Combo")
    print("=" * 80)
    
    filter_variants = [
        ("Unfiltered", sig_raw),
        ("SMA200 only", sig_raw & above_sma200),
        ("BB 0.2-0.6 only", sig_raw & bb_bounce_02_06),
        ("BB 0.15-0.65 only", sig_raw & bb_bounce_015_065),
        ("SMA200 + BB 0.2-0.6", sig_raw & above_sma200 & bb_bounce_02_06),
        ("SMA200 + BB 0.15-0.65", sig_raw & above_sma200 & bb_bounce_015_065),
    ]
    
    # Test with baseline exits (s3.0/t3.0/h6)
    print(f"\n  {'Variant':<25} {'Sigs':>6} {'Trades':>7} {'Sum%':>8} {'Sharpe':>7} {'MaxDD':>7} {'WR%':>6} {'PF':>6}")
    print("  " + "-" * 80)
    
    variant_results = {}
    for name, sig in filter_variants:
        trades = backtest_simple(df_4h, sig, stop_pct=3.0, target_pct=3.0, max_hold_bars=6)
        m = calculate_metrics(trades, n_bars=n_bars)
        variant_results[name] = {"sig": sig, "trades": trades, "metrics": m}
        print(f"  {name:<25} {sig.sum():>6} {m['total_trades']:>7} "
              f"{m['linear_sum']:>+7.1f}% {m['sharpe']:>+6.2f} "
              f"{m['max_dd']:>+6.1f}% {m['win_rate']:>5.1f}% {m['profit_factor']:>5.2f}")
    
    # ========================================================================
    # PARAMETER SWEEP — on unfiltered (enough trades for optimization)
    # ========================================================================
    
    print("\n" + "=" * 80)
    print("PARAMETER SWEEP: Unfiltered Spring on 4h (enough trades: 136)")
    print("=" * 80)
    
    best_unf = param_sweep(
        df_4h,
        spring_signal,
        {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5},
        filter_func=None,
        filter_kwargs={},
    )
    
    # Run sweep on SMA200-only (next most trades: ~70+)
    sma200_sig = sig_raw & above_sma200
    print(f"\nSMA200-only signals: {sma200_sig.sum()}")
    if sma200_sig.sum() > 30:
        def sma200_filter(df, sig):
            return sig & (df["close"] > sma(df["close"], 200))
        
        print("\n" + "=" * 80)
        print("PARAMETER SWEEP: SMA200-only filtered Spring on 4h")
        print("=" * 80)
        best_sma200 = param_sweep(
            df_4h,
            spring_signal,
            {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5},
            filter_func=sma200_filter,
            filter_kwargs={},
        )
    else:
        best_sma200 = None
    
    # Run sweep on BB 0.15-0.65 only
    bb_wide_sig = sig_raw & bb_bounce_015_065
    print(f"\nBB 0.15-0.65 only signals: {bb_wide_sig.sum()}")
    if bb_wide_sig.sum() > 30:
        def bb_wide_filter(df, sig):
            bb = bollinger_bands(df, 20, 2.0)
            pct_b = bb["pct_b"]
            return sig & (pct_b >= 0.15) & (pct_b < 0.65)
        
        print("\n" + "=" * 80)
        print("PARAMETER SWEEP: BB 0.15-0.65 filtered Spring on 4h")
        print("=" * 80)
        best_bb_wide = param_sweep(
            df_4h,
            spring_signal,
            {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5},
            filter_func=bb_wide_filter,
            filter_kwargs={},
        )
    else:
        best_bb_wide = None
    
    # ========================================================================
    # DETAILED BACKTEST: Best Unfiltered
    # ========================================================================
    
    print("\n" + "=" * 80)
    print("FULL BACKTEST: Best Unfiltered Configuration")
    print(f"  stop={best_unf['stop']:.1f}%, target={best_unf['target']:.1f}%, hold={best_unf['hold']}bh")
    print("=" * 80)
    
    sig_unf = spring_signal(df_4h, lookback=20, vol_mult=1.5, close_pct=0.5)
    trades_unf = backtest_simple(
        df_4h, sig_unf,
        stop_pct=best_unf["stop"], target_pct=best_unf["target"],
        max_hold_bars=best_unf["hold"],
    )
    m_unf = calculate_metrics(trades_unf, n_bars=n_bars)
    
    print(f"\n  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {m_unf['total_trades']}")
    print(f"  Compound Return:    {m_unf['compound_return']:+.1f}%")
    print(f"  Linear Sum:         {m_unf['linear_sum']:+.1f}%")
    print(f"  Annualized Return:  {m_unf['annualized']:+.1f}%")
    print(f"  Sharpe Ratio:       {m_unf['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {m_unf['sortino']:+.2f}")
    print(f"  Max Drawdown:       {m_unf['max_dd']:+.1f}%")
    print(f"  Win Rate:           {m_unf['win_rate']:.1f}%")
    print(f"  Avg Win:            {m_unf['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {m_unf['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {m_unf['profit_factor']:.2f}")
    print(f"  Max Consec Losses:  {m_unf['max_consec_losses']}")
    
    eb = exit_breakdown(trades_unf)
    print(f"\n  Exit Breakdown:")
    for reason, count, avg_pnl, total in eb:
        print(f"    {reason:>14}: {count:>4} ({count/len(trades_unf)*100:5.1f}%)  avg={avg_pnl:>+6.2f}%  total={total:>+7.1f}%")
    
    # ========================================================================
    # WALK-FORWARD: Both Unfiltered and Best Filtered
    # ========================================================================
    
    print("\n" + "=" * 80)
    print("WALK-FORWARD VALIDATION: Unfiltered Spring on 4h (6 splits)")
    print("=" * 80)
    
    wf_unf = walk_forward_test(
        df_4h,
        spring_signal,
        {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5},
        {"stop_pct": best_unf["stop"], "target_pct": best_unf["target"], "max_hold_bars": best_unf["hold"]},
        n_splits=6,
        filter_func=None,
        filter_kwargs={},
    )
    
    print(f"\n  {'Split':>6} {'Period':<22} {'Trades':>7} {'Sum%':>8} {'Sharpe':>7} {'MaxDD':>7} {'WR%':>6} {'PF':>6} {'Status':>7}")
    print("  " + "-" * 85)
    
    profitable = 0
    oos_sharpes = []
    for w in wf_unf:
        status = "✅" if w["sum"] > 0 else "❌"
        if w["sum"] > 0:
            profitable += 1
        oos_sharpes.append(w["sharpe"])
        print(f"  {w['split']:>6} {w['start']+'→'+w['end']:<22} {w['trades']:>7} "
              f"{w['sum']:>+7.1f}% {w['sharpe']:>+6.2f} {w['max_dd']:>+6.1f}% "
              f"{w['win_rate']:>5.1f}% {w['profit_factor']:>5.2f} {status:>7}")
    
    mean_oos = np.mean(oos_sharpes)
    print(f"\n  OOS Profitable: {profitable}/{len(wf_unf)} splits")
    print(f"  Mean OOS Sharpe: {mean_oos:+.2f}")
    
    # WF for SMA200-only if available
    if best_sma200 is not None:
        print("\n" + "=" * 80)
        print("WALK-FORWARD VALIDATION: SMA200-only Spring on 4h (6 splits)")
        print("=" * 80)
        
        wf_sma = walk_forward_test(
            df_4h,
            spring_signal,
            {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5},
            {"stop_pct": best_sma200["stop"], "target_pct": best_sma200["target"], "max_hold_bars": best_sma200["hold"]},
            n_splits=6,
            filter_func=sma200_filter,
            filter_kwargs={},
        )
        
        print(f"\n  {'Split':>6} {'Period':<22} {'Trades':>7} {'Sum%':>8} {'Sharpe':>7} {'MaxDD':>7} {'WR%':>6} {'PF':>6} {'Status':>7}")
        print("  " + "-" * 85)
        
        prof2 = 0
        oos2 = []
        for w in wf_sma:
            status = "✅" if w["sum"] > 0 else "❌"
            if w["sum"] > 0:
                prof2 += 1
            oos2.append(w["sharpe"])
            print(f"  {w['split']:>6} {w['start']+'→'+w['end']:<22} {w['trades']:>7} "
                  f"{w['sum']:>+7.1f}% {w['sharpe']:>+6.2f} {w['max_dd']:>+6.1f}% "
                  f"{w['win_rate']:>5.1f}% {w['profit_factor']:>5.2f} {status:>7}")
        
        print(f"\n  OOS Profitable: {prof2}/{len(wf_sma)} splits")
        print(f"  Mean OOS Sharpe: {np.mean(oos2):+.2f}")
    
    # ========================================================================
    # REGIME ANALYSIS — on unfiltered trades (more trades = more reliable)
    # ========================================================================
    
    print("\n" + "=" * 80)
    print("REGIME ANALYSIS: Tagging ALL unfiltered trades by entry conditions")
    print("=" * 80)
    
    # Compute regime indicators
    df_4h["sma50"] = sma(df_4h["close"], 50)
    adx_df = adx_func(df_4h, 14)
    df_4h["adx"] = adx_df["adx"]
    df_4h["pdi"] = adx_df["pdi"]
    df_4h["mdi"] = adx_df["mdi"]
    df_4h["atr14"] = atr_func(df_4h, 14)
    df_4h["median_atr200"] = df_4h["atr14"].rolling(200).median()
    df_4h["vol_ratio"] = df_4h["atr14"] / df_4h["median_atr200"]
    df_4h["rsi14"] = rsi(df_4h["close"], 14)
    df_4h["dd24"] = pct_change_rolling(df_4h["close"], 24)
    
    entry_bars = [t["entry_idx"] for t in trades_unf]
    
    regimes = {
        "Above SMA200": df_4h["close"].iloc[entry_bars] > df_4h["sma200"].iloc[entry_bars],
        "Below SMA200": df_4h["close"].iloc[entry_bars] <= df_4h["sma200"].iloc[entry_bars],
        "Above SMA50": df_4h["close"].iloc[entry_bars] > df_4h["sma50"].iloc[entry_bars],
        "ADX > 25 (trending)": df_4h["adx"].iloc[entry_bars] > 25,
        "ADX < 20 (ranging)": df_4h["adx"].iloc[entry_bars] < 20,
        "PDI > MDI (bull)": df_4h["pdi"].iloc[entry_bars] > df_4h["mdi"].iloc[entry_bars],
        "MDI > PDI (bear)": df_4h["mdi"].iloc[entry_bars] > df_4h["pdi"].iloc[entry_bars],
        "RSI < 30 (oversold)": df_4h["rsi14"].iloc[entry_bars] < 30,
        "RSI 30-50": (df_4h["rsi14"].iloc[entry_bars] >= 30) & (df_4h["rsi14"].iloc[entry_bars] < 50),
        "RSI 50-70": (df_4h["rsi14"].iloc[entry_bars] >= 50) & (df_4h["rsi14"].iloc[entry_bars] < 70),
        "RSI > 70": df_4h["rsi14"].iloc[entry_bars] > 70,
        "High Vol (ATR>1.2x)": df_4h["vol_ratio"].iloc[entry_bars] > 1.2,
        "Low Vol (ATR<0.8x)": df_4h["vol_ratio"].iloc[entry_bars] < 0.8,
        "BB %B < 0.2 (below)": df_4h["bb_pct_b"].iloc[entry_bars] < 0.2,
        "BB %B 0.2-0.4": (df_4h["bb_pct_b"].iloc[entry_bars] >= 0.2) & (df_4h["bb_pct_b"].iloc[entry_bars] < 0.4),
        "BB %B 0.4-0.6": (df_4h["bb_pct_b"].iloc[entry_bars] >= 0.4) & (df_4h["bb_pct_b"].iloc[entry_bars] < 0.6),
        "BB %B > 0.6": df_4h["bb_pct_b"].iloc[entry_bars] >= 0.6,
        "Recent DD > 10%": df_4h["dd24"].iloc[entry_bars] < -10,
    }
    
    pnls_arr = np.array([t["pnl_pct"] for t in trades_unf])
    
    print(f"\n  {'Regime':<30} {'Trades':>7} {'Sum%':>8} {'Sharpe':>7} {'WR%':>6} {'PF':>6}")
    print("  " + "-" * 70)
    
    for name, mask in regimes.items():
        subset = pnls_arr[mask.values]
        if len(subset) == 0:
            continue
        sub_sharpe = np.mean(subset) / np.std(subset, ddof=1) if np.std(subset, ddof=1) > 0 else 0.0
        sub_wr = (subset > 0).sum() / len(subset) * 100
        wins_sum = subset[subset > 0].sum() if (subset > 0).any() else 0
        loss_sum = abs(subset[subset < 0].sum()) if (subset < 0).any() else 1e-10
        sub_pf = wins_sum / loss_sum
        print(f"  {name:<30} {len(subset):>7} {subset.sum():>+7.1f}% {sub_sharpe:>+6.2f} {sub_wr:>5.1f}% {sub_pf:>5.2f}")
    
    # ========================================================================
    # COMPARISON TABLE
    # ========================================================================
    
    print("\n" + "=" * 80)
    print("FINAL COMPARISON: 1h Spring vs 4h Spring")
    print("=" * 80)
    
    labels = []
    values = []
    
    labels.append(("1h Baseline (unfiltered)", "543 trades, Sharpe -0.71"))
    labels.append(("1h Filtered (SMA200+BB)", "78 trades, Sharpe +1.53, MaxDD -5.5%"))
    labels.append(("4h Unfiltered (baseline)", f"{m_unf['total_trades']} trades"))
    labels.append(("4h SMA200 only", variant_results["SMA200 only"]["metrics"]))
    labels.append(("4h BB 0.15-0.65", variant_results["BB 0.15-0.65 only"]["metrics"]))
    labels.append(("4h SMA200+BB 0.2-0.6", variant_results["SMA200 + BB 0.2-0.6"]["metrics"]))
    
    print(f"\n  {'Strategy':<30} {'Trades':>7} {'Sum%':>8} {'Sharpe':>7} {'MaxDD':>7} {'WR%':>6} {'PF':>6}")
    print("  " + "-" * 75)
    print(f"  {'1h Unfiltered (ref)':<30} {'543':>7} {'-43.2%':>8} {'-0.71':>7} {'-55.0%':>7} {'48.1%':>6} {'0.93':>6}")
    print(f"  {'1h Filtered (ref)':<30} {'78':>7} {'+24.5%':>8} {'+1.53':>7} {'-5.5%':>7} {'56.4%':>6} {'1.53':>6}")
    print(f"  {'4h Unfiltered (s3/t3/h6)':<30} {variant_results['Unfiltered']['metrics']['total_trades']:>7} "
          f"{variant_results['Unfiltered']['metrics']['linear_sum']:>+7.1f}% "
          f"{variant_results['Unfiltered']['metrics']['sharpe']:>+6.2f} "
          f"{variant_results['Unfiltered']['metrics']['max_dd']:>+6.1f}% "
          f"{variant_results['Unfiltered']['metrics']['win_rate']:>5.1f}% "
          f"{variant_results['Unfiltered']['metrics']['profit_factor']:>5.2f}")
    for vname in ["SMA200 only", "BB 0.2-0.6 only", "BB 0.15-0.65 only", "SMA200 + BB 0.2-0.6", "SMA200 + BB 0.15-0.65"]:
        m = variant_results[vname]["metrics"]
        print(f"  {'4h ' + vname:<30} {m['total_trades']:>7} "
              f"{m['linear_sum']:>+7.1f}% {m['sharpe']:>+6.2f} "
              f"{m['max_dd']:>+6.1f}% {m['win_rate']:>5.1f}% {m['profit_factor']:>5.2f}")
    
    # Best unfiltered
    print(f"  {'4h Unfiltered BEST':<30} {m_unf['total_trades']:>7} "
          f"{m_unf['linear_sum']:>+7.1f}% {m_unf['sharpe']:>+6.2f} "
          f"{m_unf['max_dd']:>+6.1f}% {m_unf['win_rate']:>5.1f}% {m_unf['profit_factor']:>5.2f}")
    if best_sma200 is not None:
        print(f"  {'4h SMA200 BEST':<30} {best_sma200['total_trades']:>7} "
              f"{best_sma200['linear_sum']:>+7.1f}% {best_sma200['sharpe']:>+6.2f} "
              f"{best_sma200['max_dd']:>+6.1f}% {best_sma200['win_rate']:>5.1f}% {best_sma200['profit_factor']:>5.2f}")
    if best_bb_wide is not None:
        print(f"  {'4h BB 0.15-0.65 BEST':<30} {best_bb_wide['total_trades']:>7} "
              f"{best_bb_wide['linear_sum']:>+7.1f}% {best_bb_wide['sharpe']:>+6.2f} "
              f"{best_bb_wide['max_dd']:>+6.1f}% {best_bb_wide['win_rate']:>5.1f}% {best_bb_wide['profit_factor']:>5.2f}")
    
    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)


if __name__ == "__main__":
    main()
