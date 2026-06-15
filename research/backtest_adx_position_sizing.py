"""
ADX-Based Position Sizing — BB Breakout + Spring Reversal Portfolio Optimization
=================================================================================

Hypothesis: Dynamically allocating capital between BB Breakout (momentum, performs
best when ADX > 25) and Spring Reversal (mean-reversion, performs best when ADX < 20)
based on ADX regime will:
1. Reduce Max Drawdown (draw less capital to losing strategy in wrong regime)
2. Improve risk-adjusted returns (Sharpe, Sortino)
3. Smooth the equity curve (lower volatility)

Approach: Run each strategy independently with BacktestEngine. At trade entry,
scale position size based on ADX at entry time. Merge trades with variable
capital allocation, compute combined equity curve.

Capital allocation rules (ADX-based):
- ADX > 25 (trending):   BB gets fraction_B_trend, Spring gets fraction_S_trend
- ADX < 20 (ranging):    BB gets fraction_B_range, Spring gets fraction_S_range
- ADX 20-25 (transition): BB/Spring each get 0.5

Sweep: fraction_B_trend from 0.5 to 0.9, fraction_B_range from 0.1 to 0.5
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd
import itertools

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, bollinger_bands, adx as adx_func,
)

# ============================================================================
# Spring Reversal Signal (inline)
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


# ============================================================================
# Strategy Classes
# ============================================================================

class BBUpperBreakoutNoSMA(Strategy):
    """BB Upper Breakout without SMA200 filter (better Sharpe)."""
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 50,
        "bb_std": 2.5,
    }

    @property
    def name(self) -> str:
        return "BB_Upper_Breakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        bb = bollinger_bands(df, period=50, std=2.5)
        signal = df["close"] > bb["upper"]
        return signal.astype(int)


class SpringFiltered(Strategy):
    """Spring Reversal with SMA200 + BB %B 0.2-0.6 filters."""
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"

    DEFAULT_PARAMS = {
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
    }

    @property
    def name(self) -> str:
        return "Spring_Filtered"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        base = spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5)
        sma200 = sma(df["close"], 200)
        bb = bollinger_bands(df, 20, 2.0)
        bb_filter = (bb["pct_b"] >= 0.2) & (bb["pct_b"] < 0.6)
        sma_filter = df["close"] > sma200
        filtered = base & bb_filter & sma_filter
        return filtered.astype(int)


# ============================================================================
# ADX-Based Position Scaler
# ============================================================================

def compute_adx_regime(df, period=14):
    """Compute ADX regime labels for each bar.
    
    Returns dict with keys:
      'adx': Series of ADX values
      'regime': Series with 'trending' / 'transition' / 'ranging'
    """
    adx_df = adx_func(df, period=period)
    adx = adx_df["adx"]
    
    def classify(v):
        if pd.isna(v):
            return "transition"
        if v > 25:
            return "trending"
        elif v < 20:
            return "ranging"
        else:
            return "transition"
    
    regime = adx.apply(classify)
    return {"adx": adx, "regime": regime}


def scale_trades_by_adx(
    bb_trades, spring_trades, df, adx_data,
    frac_trend=(0.8, 0.2),   # (BB_frac, Spring_frac) when ADX > 25
    frac_range=(0.2, 0.8),   # (BB_frac, Spring_frac) when ADX > 25
):
    """Scale trade PnL by ADX-based position sizing.
    
    Each strategy runs with full capital. Then we scale each trade
    by its allocation fraction based on ADX at entry. The sum of
    both strategies' allocations = 1.0 (full capital deployed per regime).
    
    In 'transition' (ADX 20-25): equal 0.5/0.5 allocation.
    """
    # Build ADX lookup: timestamp -> regime
    adx_lookup = {}
    for i in range(len(df)):
        ts = int(df.index[i].timestamp() * 1000)
        adx_lookup[ts] = adx_data["regime"].iloc[i]
    
    scaled_bb = []
    for t in bb_trades:
        regime = adx_lookup.get(t.entry_time, "transition")
        if regime == "trending":
            frac = frac_trend[0]
        elif regime == "ranging":
            frac = frac_range[0]
        else:
            frac = 0.5
        # Scale pnl_pct by fraction of capital allocated
        new_t = type(t)(**t.__dict__)  # shallow copy
        new_t.pnl_pct = t.pnl_pct * frac
        new_t.pnl_abs = t.pnl_abs * frac
        new_t.regime = {**t.regime, "adx_regime": regime, "alloc_frac": frac}
        scaled_bb.append(new_t)
    
    scaled_spring = []
    for t in spring_trades:
        regime = adx_lookup.get(t.entry_time, "transition")
        if regime == "trending":
            frac = frac_trend[1]
        elif regime == "ranging":
            frac = frac_range[1]
        else:
            frac = 0.5
        new_t = type(t)(**t.__dict__)
        new_t.pnl_pct = t.pnl_pct * frac
        new_t.pnl_abs = t.pnl_abs * frac
        new_t.regime = {**t.regime, "adx_regime": regime, "alloc_frac": frac}
        scaled_spring.append(new_t)
    
    return scaled_bb + scaled_spring


# ============================================================================
# Combined Metrics Calculation
# ============================================================================

PERIODS_PER_YEAR = 365 * 24


def compute_combined_metrics(trades, df, initial_capital=10_000.0):
    """Compute metrics from a combined list of scaled trades."""
    if not trades:
        return None, pd.Series(initial_capital, index=df.index), pd.Series(0.0, index=df.index)
    
    sorted_trades = sorted(trades, key=lambda t: t.exit_time)
    
    exit_times = []
    factors = []
    for t in sorted_trades:
        exit_times.append(pd.Timestamp(t.exit_time, unit="ms"))
        factors.append(1.0 + t.pnl_pct / 100.0)
    
    equity_jumps = pd.Series(factors, index=exit_times, dtype=float)
    equity_jumps.sort_index(inplace=True)
    cumulative = equity_jumps.cumprod()
    
    curve = pd.Series(initial_capital, index=df.index, dtype=float)
    for ts, factor in cumulative.items():
        mask = df.index >= ts
        if mask.any():
            curve[mask] = initial_capital * factor
    
    dd_curve = (curve / curve.cummax() - 1) * 100
    
    # Sharpe/Sortino
    daily_returns = curve.resample("1D").last().pct_change().dropna()
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(365))
    else:
        sharpe = 0.0
    
    downside = daily_returns[daily_returns < 0]
    if len(downside) > 0 and downside.std() > 0:
        sortino = float(daily_returns.mean() / downside.std() * np.sqrt(365))
    else:
        sortino = 0.0
    
    # Trade-level metrics
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0
    
    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    max_consec = 0
    consec = 0
    for t in sorted_trades:
        if t.pnl_pct <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    
    final_equity = curve.iloc[-1]
    compound_return = (final_equity / initial_capital - 1) * 100
    linear_sum = sum(t.pnl_pct for t in trades)
    
    total_days = (df.index[-1] - df.index[0]).total_seconds() / 86400
    total_years = total_days / 365.25
    annualized = (final_equity / initial_capital) ** (1 / max(total_years, 1)) - 1
    
    max_dd = dd_curve.min()
    
    exit_counts = Counter(t.exit_reason for t in trades)
    exit_detail = {}
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        subset = [t for t in trades if t.exit_reason == reason]
        count = len(subset)
        pct = count / len(trades) * 100 if trades else 0
        avg = np.mean([t.pnl_pct for t in subset]) if subset else 0
        total = sum(t.pnl_pct for t in subset)
        exit_detail[reason] = (count, pct, avg, total)
    
    return {
        "total_trades": len(trades),
        "compound_return": compound_return,
        "linear_sum": linear_sum,
        "annualized_return": annualized * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_consec_losses": max_consec,
        "exit_detail": exit_detail,
        "final_equity": final_equity,
    }, curve, dd_curve


# ============================================================================
# Walk-Forward
# ============================================================================

def walk_forward_adx(
    df, bb_strategy, spring_strategy,
    bb_exit, spring_exit,
    adx_data,
    frac_trend, frac_range,
    n_splits=7,
):
    """Walk-forward with ADX-based position sizing."""
    n = len(df)
    slot = n // (n_splits + 2)
    
    splits_results = []
    
    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        oos_df = df.iloc[start:end]
        
        # Get ADX for this OOS window
        oos_adx = {
            "adx": adx_data["adx"].iloc[start:end],
            "regime": adx_data["regime"].iloc[start:end],
        }
        
        # Run BB
        engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_bb = engine_bb.run(
            oos_df, bb_strategy, symbol="BTC/USDT",
            stop_loss_pct=bb_exit["stop_pct"],
            take_profit_pct=bb_exit["target_pct"],
            max_hold_bars=bb_exit["hold_hours"],
        )
        
        # Run Spring
        engine_sp = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_sp = engine_sp.run(
            oos_df, spring_strategy, symbol="BTC/USDT",
            stop_loss_pct=spring_exit["stop_pct"],
            take_profit_pct=spring_exit["target_pct"],
            max_hold_bars=spring_exit["hold_hours"],
        )
        
        # Scale by ADX
        scaled = scale_trades_by_adx(
            result_bb.trades, result_sp.trades,
            oos_df, oos_adx, frac_trend, frac_range,
        )
        
        metrics, curve, dd = compute_combined_metrics(scaled, oos_df)
        
        start_dt = oos_df.index[0].strftime("%Y-%m")
        end_dt = oos_df.index[-1].strftime("%Y-%m")
        status = "✅" if metrics["linear_sum"] > 0 else "❌"
        
        splits_results.append({
            "split": s + 1,
            "period": f"{start_dt}→{end_dt}",
            "trades": metrics["total_trades"],
            "sum": metrics["linear_sum"],
            "sharpe": metrics["sharpe"],
            "max_dd": metrics["max_drawdown"],
            "status": status,
        })
    
    return splits_results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("ADX-BASED POSITION SIZING: BB + SPRING PORTFOLIO OPTIMIZATION")
    print("=" * 70)
    
    # Load data
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nOKX BTC/USDT 1h: {len(df):,} bars, {df.index[0]} → {df.index[-1]}")
    
    # Pre-compute ADX
    print("Computing ADX...")
    adx_data = compute_adx_regime(df)
    regime_counts = adx_data["regime"].value_counts()
    print(f"  Regime distribution: trending={regime_counts.get('trending',0):,} "
          f"transition={regime_counts.get('transition',0):,} "
          f"ranging={regime_counts.get('ranging',0):,}")
    
    # Strategy configs
    bb_strategy = BBUpperBreakoutNoSMA()
    spring_strategy = SpringFiltered()
    
    bb_exit = {"stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10}
    spring_exit = {"stop_pct": 3.0, "target_pct": 3.0, "hold_hours": 16}
    
    # =========================================================================
    # BASELINE: Run individual backtests
    # =========================================================================
    print(f"\n{'='*70}")
    print("BASELINE: INDIVIDUAL STRATEGIES (Full Capital)")
    print(f"{'='*70}")
    
    engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_bb = engine_bb.run(df, bb_strategy, symbol="BTC/USDT",
                               stop_loss_pct=bb_exit["stop_pct"],
                               take_profit_pct=bb_exit["target_pct"],
                               max_hold_bars=bb_exit["hold_hours"])
    
    engine_sp = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_sp = engine_sp.run(df, spring_strategy, symbol="BTC/USDT",
                                stop_loss_pct=spring_exit["stop_pct"],
                                take_profit_pct=spring_exit["target_pct"],
                                max_hold_bars=spring_exit["hold_hours"])
    
    print(f"\n  BB Breakout (s1.2/t4.0/h10):")
    print(f"    Trades: {result_bb.metrics.total_trades}")
    print(f"    Compound: {result_bb.metrics.total_return_pct:+.1f}%")
    print(f"    Linear Sum: {sum(t.pnl_pct for t in result_bb.trades):+.1f}%")
    print(f"    Sharpe: {result_bb.metrics.sharpe_ratio:+.2f}")
    print(f"    Sortino: {result_bb.metrics.sortino_ratio:+.2f}")
    print(f"    Max DD: {result_bb.metrics.max_drawdown_pct:.1f}%")
    print(f"    Win Rate: {result_bb.metrics.win_rate_pct:.1f}%")
    print(f"    PF: {result_bb.metrics.profit_factor:.2f}")
    
    print(f"\n  Spring Filtered (s3.0/t3.0/h16):")
    print(f"    Trades: {result_sp.metrics.total_trades}")
    print(f"    Compound: {result_sp.metrics.total_return_pct:+.1f}%")
    print(f"    Linear Sum: {sum(t.pnl_pct for t in result_sp.trades):+.1f}%")
    print(f"    Sharpe: {result_sp.metrics.sharpe_ratio:+.2f}")
    print(f"    Sortino: {result_sp.metrics.sortino_ratio:+.2f}")
    print(f"    Max DD: {result_sp.metrics.max_drawdown_pct:.1f}%")
    print(f"    Win Rate: {result_sp.metrics.win_rate_pct:.1f}%")
    print(f"    PF: {result_sp.metrics.profit_factor:.2f}")
    
    # =========================================================================
    # EQUAL-WEIGHT BASELINE (50/50 in all regimes)
    # =========================================================================
    print(f"\n{'='*70}")
    print("BASELINE: EQUAL-WEIGHT (50/50) COMBINED")
    print(f"{'='*70}")
    
    eq_trades = scale_trades_by_adx(
        result_bb.trades, result_sp.trades, df, adx_data,
        frac_trend=(0.5, 0.5), frac_range=(0.5, 0.5),
    )
    eq_metrics, eq_curve, eq_dd = compute_combined_metrics(eq_trades, df)
    
    print(f"\n  Total Trades:       {eq_metrics['total_trades']}")
    print(f"  Compound Return:    {eq_metrics['compound_return']:+.1f}%")
    print(f"  Linear Sum:         {eq_metrics['linear_sum']:+.1f}%")
    print(f"  Annualized:         {eq_metrics['annualized_return']:+.1f}%")
    print(f"  Sharpe Ratio:       {eq_metrics['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {eq_metrics['sortino']:+.2f}")
    print(f"  Max Drawdown:       {eq_metrics['max_drawdown']:.1f}%")
    print(f"  Win Rate:           {eq_metrics['win_rate']:.1f}%")
    print(f"  Avg Win:            {eq_metrics['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {eq_metrics['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {eq_metrics['profit_factor']:.2f}")
    print(f"  Max Consec Losses:  {eq_metrics['max_consec_losses']}")
    
    # Exit breakdown
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        count, pct, avg, total = eq_metrics["exit_detail"][reason]
        if count > 0:
            print(f"    {reason:15s}: {count:>4,d} ({pct:>5.1f}%)  "
                  f"avg={avg:>+6.2f}%  total={total:>+8.1f}%")
    
    # =========================================================================
    # ADX-BASED ALLOCATION SWEEP
    # =========================================================================
    print(f"\n{'='*70}")
    print("ADX-BASED ALLOCATION SWEEP")
    print(f"{'='*70}")
    
    # Sweep: BB fraction in trending regime from 0.5 to 0.9
    #         BB fraction in ranging regime from 0.1 to 0.5
    # Transition regime always 50/50
    
    bb_trend_values = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9]
    bb_range_values = [0.1, 0.2, 0.3, 0.4, 0.5]
    
    results = []
    
    for bb_t, bb_r in itertools.product(bb_trend_values, bb_range_values):
        # When BB gets bb_t in trending, Spring gets (1-bb_t)
        frac_trend = (bb_t, 1.0 - bb_t)
        frac_range = (bb_r, 1.0 - bb_r)
        
        scaled = scale_trades_by_adx(
            result_bb.trades, result_sp.trades, df, adx_data,
            frac_trend=frac_trend, frac_range=frac_range,
        )
        
        metrics, _, _ = compute_combined_metrics(scaled, df)
        
        results.append({
            "bb_trend": bb_t,
            "bb_range": bb_r,
            "sp_trend": 1.0 - bb_t,
            "sp_range": 1.0 - bb_r,
            "sharpe": metrics["sharpe"],
            "sortino": metrics["sortino"],
            "compound": metrics["compound_return"],
            "linear_sum": metrics["linear_sum"],
            "max_dd": metrics["max_drawdown"],
            "win_rate": metrics["win_rate"],
            "pf": metrics["profit_factor"],
        })
    
    # Sort by Sharpe
    results.sort(key=lambda r: r["sharpe"], reverse=True)
    
    # Print sweep results
    print(f"\n  {'BB_T':>5s} {'BB_R':>5s} {'SP_T':>5s} {'SP_R':>5s} "
          f"{'Sharpe':>8s} {'Sortino':>8s} {'Cmpd%':>8s} "
          f"{'MaxDD%':>7s} {'WR%':>6s} {'PF':>5s}")
    print(f"  {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*8} {'-'*8} {'-'*8} "
          f"{'-'*7} {'-'*6} {'-'*5}")
    
    for r in results:
        print(f"  {r['bb_trend']:>5.2f} {r['bb_range']:>5.2f} "
              f"{r['sp_trend']:>5.2f} {r['sp_range']:>5.2f} "
              f"{r['sharpe']:>+8.2f} {r['sortino']:>+8.2f} "
              f"{r['compound']:>+8.1f}% {r['max_dd']:>7.1f}% "
              f"{r['win_rate']:>6.1f}% {r['pf']:>.2f}")
    
    # =========================================================================
    # BEST CONFIGURATION — FULL DETAILS
    # =========================================================================
    best = results[0]
    
    print(f"\n{'='*70}")
    print(f"BEST CONFIGURATION: Full Detail")
    print(f"{'='*70}")
    
    print(f"\n  Allocation:")
    print(f"    Trending (ADX>25): BB={best['bb_trend']:.0%} / Spring={best['sp_trend']:.0%}")
    print(f"    Ranging  (ADX<20): BB={best['bb_range']:.0%} / Spring={best['sp_range']:.0%}")
    print(f"    Transition (20-25): BB=50% / Spring=50%")
    
    # Re-run with best config for full detail
    best_frac_trend = (best["bb_trend"], best["sp_trend"])
    best_frac_range = (best["bb_range"], best["sp_range"])
    
    best_scaled = scale_trades_by_adx(
        result_bb.trades, result_sp.trades, df, adx_data,
        frac_trend=best_frac_trend, frac_range=best_frac_range,
    )
    best_metrics, best_curve, best_dd = compute_combined_metrics(best_scaled, df)
    
    print(f"\n  Full Backtest Results (OKX BTC/USDT 1h, 2019-2026):")
    print(f"  {'─'*55}")
    print(f"  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {best_metrics['total_trades']}")
    print(f"  Compound Return:    {best_metrics['compound_return']:+.1f}%")
    print(f"  Linear Sum:         {best_metrics['linear_sum']:+.1f}%")
    print(f"  Annualized Return:  {best_metrics['annualized_return']:+.1f}%")
    print(f"  Sharpe Ratio:       {best_metrics['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {best_metrics['sortino']:+.2f}")
    print(f"  Max Drawdown:       {best_metrics['max_drawdown']:.1f}%")
    print(f"  Win Rate:           {best_metrics['win_rate']:.1f}%")
    print(f"  Avg Win:            {best_metrics['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {best_metrics['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {best_metrics['profit_factor']:.2f}")
    print(f"  Max Consec Losses:  {best_metrics['max_consec_losses']}")
    
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        count, pct, avg, total = best_metrics["exit_detail"][reason]
        if count > 0:
            print(f"    {reason:15s}: {count:>4,d} ({pct:>5.1f}%)  "
                  f"avg={avg:>+6.2f}%  total={total:>+8.1f}%")
    
    # =========================================================================
    # COMPARISON TABLE
    # =========================================================================
    print(f"\n{'='*70}")
    print(f"COMPARISON: Baseline vs Equal-Weight vs ADX-Sized")
    print(f"{'='*70}")
    
    # Also compute full-capital combined (100/100, no scaling)
    full_trades = result_bb.trades + result_sp.trades
    full_metrics, _, _ = compute_combined_metrics(full_trades, df)
    
    print(f"\n  {'Metric':25s} {'BB Only':>12s} {'Spring Only':>12s} "
          f"{'Full 100+100':>12s} {'Equal 50/50':>12s} {'ADX-Sized':>12s}")
    print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*12}")
    
    names = ["BB Only", "Spring Only", "Full 100+100", "Equal 50/50", "ADX-Sized"]
    m_list = [
        result_bb.metrics, result_sp.metrics, full_metrics, eq_metrics, best_metrics,
    ]
    
    for metric_key, label in [
        ("sharpe", "Sharpe Ratio"),
        ("sortino", "Sortino Ratio"),
        ("compound_return", "Compound Return %"),
        ("linear_sum", "Linear Sum %"),
        ("annualized_return", "Annualized Return %"),
        ("max_drawdown", "Max Drawdown %"),
        ("win_rate", "Win Rate %"),
        ("profit_factor", "Profit Factor"),
        ("total_trades", "Total Trades"),
        ("max_consec_losses", "Max Consec Losses"),
    ]:
        vals = []
        for i, m in enumerate(m_list):
            if metric_key == "sharpe":
                v = m.sharpe_ratio if hasattr(m, 'sharpe_ratio') else m.get("sharpe", 0)
                vals.append(f"{v:>+11.2f}")
            elif metric_key == "sortino":
                v = m.sortino_ratio if hasattr(m, 'sortino_ratio') else m.get("sortino", 0)
                vals.append(f"{v:>+11.2f}")
            elif metric_key == "compound_return":
                v = m.total_return_pct if hasattr(m, 'total_return_pct') else m.get("compound_return", 0)
                vals.append(f"{v:>+10.1f}%")
            elif metric_key == "linear_sum":
                if i < 2:
                    v = sum(t.pnl_pct for t in (result_bb if i==0 else result_sp).trades)
                else:
                    v = m.get("linear_sum", 0)
                vals.append(f"{v:>+10.1f}%")
            elif metric_key == "annualized_return":
                v = m.annualized_return_pct if hasattr(m, 'annualized_return_pct') else m.get("annualized_return", 0)
                vals.append(f"{v:>+10.1f}%")
            elif metric_key == "max_drawdown":
                v = m.max_drawdown_pct if hasattr(m, 'max_drawdown_pct') else m.get("max_drawdown", 0)
                vals.append(f"{v:>10.1f}%")
            elif metric_key == "win_rate":
                v = m.win_rate_pct if hasattr(m, 'win_rate_pct') else m.get("win_rate", 0)
                vals.append(f"{v:>10.1f}%")
            elif metric_key == "profit_factor":
                v = m.profit_factor if hasattr(m, 'profit_factor') else m.get("profit_factor", 0)
                vals.append(f"{v:>11.2f}")
            elif metric_key == "total_trades":
                v = m.total_trades if hasattr(m, 'total_trades') else m.get("total_trades", 0)
                vals.append(f"{v:>12,d}")
            elif metric_key == "max_consec_losses":
                if i < 2:
                    pnls = [t.pnl_pct for t in (result_bb if i==0 else result_sp).trades]
                    consec = 0; maxc = 0
                    for p in pnls:
                        if p <= 0: consec += 1; maxc = max(maxc, consec)
                        else: consec = 0
                    v = maxc
                else:
                    v = m.get("max_consec_losses", 0)
                vals.append(f"{v:>12,d}")
        
        print(f"  {label:25s} {' '.join(vals)}")
    
    # =========================================================================
    # WALK-FORWARD VALIDATION
    # =========================================================================
    print(f"\n{'='*70}")
    print(f"WALK-FORWARD VALIDATION (Best Config)")
    print(f"{'='*70}")
    
    wf_results = walk_forward_adx(
        df, bb_strategy, spring_strategy,
        bb_exit, spring_exit,
        adx_data,
        frac_trend=best_frac_trend,
        frac_range=best_frac_range,
        n_splits=7,
    )
    
    for wf in wf_results:
        print(f"  Split {wf['split']}: {wf['period']}  "
              f"trades={wf['trades']}  sum={wf['sum']:+.1f}%  "
              f"sharpe={wf['sharpe']:+.2f}  {wf['status']}")
    
    profitable = sum(1 for wf in wf_results if wf["sum"] > 0)
    mean_sharpe = np.mean([wf["sharpe"] for wf in wf_results])
    total_sum = sum(wf["sum"] for wf in wf_results)
    
    print(f"\n  {profitable}/{len(wf_results)} OOS profitable | "
          f"Mean OOS Sharpe: {mean_sharpe:+.2f} | "
          f"Total OOS Sum: {total_sum:+.1f}%")
    
    # =========================================================================
    # REGIME BREAKDOWN OF TRADES
    # =========================================================================
    print(f"\n{'='*70}")
    print(f"TRADE REGIME BREAKDOWN (Best Config)")
    print(f"{'='*70}")
    
    # Group best_scaled trades by entry ADX regime
    adx_lookup = {}
    for i in range(len(df)):
        ts = int(df.index[i].timestamp() * 1000)
        adx_lookup[ts] = adx_data["regime"].iloc[i]
    
    bb_regime_trades = {"trending": [], "transition": [], "ranging": []}
    sp_regime_trades = {"trending": [], "transition": [], "ranging": []}
    
    for t in best_scaled:
        regime = adx_lookup.get(t.entry_time, "transition")
        if t.entry_signal in (1,):
            # Determine which strategy this came from
            pass  # can't easily determine which came from which
        
    # Instead, use the unscaled trades with tag
    for t in result_bb.trades:
        regime = adx_lookup.get(t.entry_time, "transition")
        bb_regime_trades.setdefault(regime, []).append(t.pnl_pct)
    for t in result_sp.trades:
        regime = adx_lookup.get(t.entry_time, "transition")
        sp_regime_trades.setdefault(regime, []).append(t.pnl_pct)
    
    for regime in ["trending", "transition", "ranging"]:
        bb = bb_regime_trades.get(regime, [])
        sp = sp_regime_trades.get(regime, [])
        print(f"\n  {regime.upper()} (ADX {'>25' if regime=='trending' else '<20' if regime=='ranging' else '20-25'}):")
        if bb:
            print(f"    BB:      {len(bb):>3d} trades, avg PnL {np.mean(bb):>+7.2f}%, sum {sum(bb):>+8.1f}%")
        if sp:
            print(f"    Spring:  {len(sp):>3d} trades, avg PnL {np.mean(sp):>+7.2f}%, sum {sum(sp):>+8.1f}%")
    
    print(f"\n{'='*70}")
    print("DONE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
