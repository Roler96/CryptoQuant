"""
BB Breakout + Spring Reversal — Combined Signal Research
=========================================================

Both strategies are individually profitable:
- BB Upper Breakout (no SMA200): Sharpe 1.55, 637 trades, DD -23.5%
- Spring filtered (SMA200 + BB %B 0.2-0.6): Sharpe 1.53, 78 trades, DD -5.5%

They operate in complementary regimes:
- BB Breakout = momentum/continuation (buy the breakout)
- Spring Reversal = reversal (buy the pullback dip in uptrend)

Hypothesis: Combining them with OR logic increases trade count, smooths the
equity curve, and improves risk-adjusted returns through diversification.

Approach: Run each strategy independently with optimal exits, combine trades,
compute combined equity curve and metrics. This avoids forcing a compromise
on exit parameters (BB needs tight stops, Spring needs wider stops).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine, _compute_drawdown_curve
from cryptoquant.engine.types import BacktestResult, PerformanceMetrics, Trade
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, ema, atr as atr_func, adx as adx_func,
    bollinger_bands, rsi, pct_change_rolling
)


# ============================================================================
# Spring Reversal Signal
# ============================================================================

def spring_signal(df, lookback=20, vol_mult=1.5, close_pct=0.5):
    """Detect Wyckoff Spring reversal pattern."""
    opens = df["open"]
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    volumes = df["volume"]

    # New low (breakdown below recent support)
    rolling_low = lows.rolling(lookback).min().shift(1)
    new_low = lows < rolling_low

    # Bullish close
    bullish_close = closes > opens

    # Close in upper portion of bar
    bar_range = highs - lows
    close_position = (closes - lows) / bar_range.replace(0, np.nan)
    close_near_high = close_position > close_pct

    # High volume confirmation
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
# Combined Metrics Calculation
# ============================================================================

PERIODS_PER_YEAR = 365 * 24  # 1h bars


def compute_combined_metrics(trades: list[Trade], df: pd.DataFrame, initial_capital: float = 10_000.0):
    """Compute metrics from a combined list of trades.

    Uses the same methodology as BacktestEngine._calculate_metrics():
    daily equity curve resampling, annualized Sharpe/Sortino.
    """
    if not trades:
        empty = {}, pd.Series(initial_capital, index=df.index, dtype=float), pd.Series(0.0, index=df.index, dtype=float)
        return empty

    # Sort by exit time
    sorted_trades = sorted(trades, key=lambda t: t.exit_time)

    # Compound equity curve
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

    # --- BacktestEngine-compatible Sharpe/Sortino ---
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

    # --- Trade-level metrics ---
    pnl_pcts = [t.pnl_pct for t in trades]
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
    linear_sum = sum(pnl_pcts)

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


def walk_forward_combined(
    df: pd.DataFrame,
    bb_strategy: Strategy,
    spring_strategy: Strategy,
    bb_exit: dict,
    spring_exit: dict,
    n_splits: int = 7,
    label: str = "",
):
    """Walk-forward validation with combined trades."""
    n = len(df)
    slot = n // (n_splits + 2)

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD COMBINED: {label} ({n_splits} splits)")
    print(f"{'='*70}")

    splits_results = []
    total_trades = 0

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        oos_df = df.iloc[start:end]

        # Run BB Backtest
        engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_bb = engine_bb.run(
            oos_df, bb_strategy,
            symbol="BTC/USDT",
            stop_loss_pct=bb_exit["stop_pct"],
            take_profit_pct=bb_exit["target_pct"],
            max_hold_bars=bb_exit["hold_hours"],
        )

        # Run Spring Backtest
        engine_spring = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_spring = engine_spring.run(
            oos_df, spring_strategy,
            symbol="BTC/USDT",
            stop_loss_pct=spring_exit["stop_pct"],
            take_profit_pct=spring_exit["target_pct"],
            max_hold_bars=spring_exit["hold_hours"],
        )

        combined_trades = result_bb.trades + result_spring.trades
        metrics, curve, dd = compute_combined_metrics(combined_trades, oos_df)

        status = "✅" if metrics["linear_sum"] > 0 else "❌"
        n_trades = metrics["total_trades"]

        start_dt = oos_df.index[0].strftime("%Y-%m")
        end_dt = oos_df.index[-1].strftime("%Y-%m")

        print(f"  Split {s+1}: {start_dt}→{end_dt}  "
              f"trades={n_trades}  sum={metrics['linear_sum']:+.1f}%  "
              f"sharpe={metrics['sharpe']:+.2f}  {status}")

        splits_results.append(metrics)
        total_trades += n_trades

    profitable = sum(1 for m in splits_results if m["linear_sum"] > 0)
    mean_sharpe = np.mean([m["sharpe"] for m in splits_results])
    total_sum = sum(m["linear_sum"] for m in splits_results)

    print(f"\n  {profitable}/{n_splits} OOS profitable | "
          f"Mean OOS Sharpe: {mean_sharpe:+.2f} | "
          f"Total OOS Sum: {total_sum:+.1f}%")

    return splits_results, profitable, mean_sharpe, total_sum


# ============================================================================
# Signal Overlap Analysis
# ============================================================================

def analyze_overlap(df: pd.DataFrame):
    """Count signal overlap between BB and Spring."""
    bb = BBUpperBreakoutNoSMA()
    spring = SpringFiltered()

    bb_sig = bb.generate_signal(df)
    spring_sig = spring.generate_signal(df)

    bb_count = (bb_sig == 1).sum()
    spring_count = (spring_sig == 1).sum()
    overlap = ((bb_sig == 1) & (spring_sig == 1)).sum()

    print(f"\n{'='*70}")
    print(f"  SIGNAL OVERLAP ANALYSIS")
    print(f"{'='*70}")
    print(f"  BB Breakout signals:   {bb_count:>6,}")
    print(f"  Spring (filtered) signals: {spring_count:>6,}")
    print(f"  Overlap (both fire):   {overlap:>6,}")
    print(f"  Overlap %:             {overlap/max(bb_count+spring_count,1)*100:.1f}%")

    return bb_count, spring_count, overlap


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("BB BREAKOUT + SPRING REVERSAL — COMBINED SIGNAL RESEARCH")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_binance = store.load("binance", "BTC/USDT", "1h")

    print(f"\nOKX: {len(df_okx):,} bars, {df_okx.index[0]} to {df_okx.index[-1]}")
    print(f"Binance: {len(df_binance):,} bars, {df_binance.index[0]} to {df_binance.index[-1]}")

    # ========================================================================
    # SIGNAL OVERLAP
    # ========================================================================
    analyze_overlap(df_okx)

    # ========================================================================
    # STRATEGY CONFIGURATIONS
    # ========================================================================

    bb_strategy = BBUpperBreakoutNoSMA()
    spring_strategy = SpringFiltered()

    # BB optimal exits: s1.2/t4.0/h10 (from STRATEGY.md optimized config)
    bb_exit = {"stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10}

    # Spring optimal exits: s3.0/t3.0/h16 (baseline, more conservative)
    spring_exit = {"stop_pct": 3.0, "target_pct": 3.0, "hold_hours": 16}

    # ========================================================================
    # INDIVIDUAL BACKTESTS (OKX)
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  INDIVIDUAL BACKTESTS — OKX BTC/USDT 1h")
    print(f"{'='*70}")

    # BB Breakout standalone
    engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_bb = engine_bb.run(
        df_okx, bb_strategy,
        symbol="BTC/USDT",
        stop_loss_pct=bb_exit["stop_pct"],
        take_profit_pct=bb_exit["target_pct"],
        max_hold_bars=bb_exit["hold_hours"],
    )

    print(f"\n  BB Upper Breakout (bb50/s2.5, s1.2/t4.0/h10):")
    print(f"    Trades: {result_bb.metrics.total_trades}")
    print(f"    Compound Return: {result_bb.metrics.total_return_pct:+.1f}%")
    print(f"    Sharpe: {result_bb.metrics.sharpe_ratio:+.2f}")
    print(f"    Max DD: {result_bb.metrics.max_drawdown_pct:.1f}%")
    print(f"    Win Rate: {result_bb.metrics.win_rate_pct:.1f}%")
    print(f"    Profit Factor: {result_bb.metrics.profit_factor:.2f}")

    # Spring standalone
    engine_spring = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_spring = engine_spring.run(
        df_okx, spring_strategy,
        symbol="BTC/USDT",
        stop_loss_pct=spring_exit["stop_pct"],
        take_profit_pct=spring_exit["target_pct"],
        max_hold_bars=spring_exit["hold_hours"],
    )

    print(f"\n  Spring Reversal (filtered, s3.0/t3.0/h16):")
    print(f"    Trades: {result_spring.metrics.total_trades}")
    print(f"    Compound Return: {result_spring.metrics.total_return_pct:+.1f}%")
    print(f"    Sharpe: {result_spring.metrics.sharpe_ratio:+.2f}")
    print(f"    Max DD: {result_spring.metrics.max_drawdown_pct:.1f}%")
    print(f"    Win Rate: {result_spring.metrics.win_rate_pct:.1f}%")
    print(f"    Profit Factor: {result_spring.metrics.profit_factor:.2f}")

    # ========================================================================
    # COMBINED BACKTEST (OKX)
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  COMBINED BACKTEST — OKX BTC/USDT 1h")
    print(f"{'='*70}")

    combined_trades = result_bb.trades + result_spring.trades
    metrics, curve, dd = compute_combined_metrics(combined_trades, df_okx)

    print(f"\n  Initial Capital:    10,000 USDT")
    print(f"  Commission:         5 bps (round-trip)")
    print(f"  Slippage:           5 bps")
    print(f"")
    print(f"  Total Trades:       {metrics['total_trades']}")
    print(f"  Compound Return:    {metrics['compound_return']:+.1f}%")
    print(f"  Linear Sum:         {metrics['linear_sum']:+.1f}%")
    print(f"  Annualized Return:  {metrics['annualized_return']:+.1f}%")
    print(f"  Sharpe Ratio:       {metrics['sharpe']:+.2f}")
    print(f"  Sortino Ratio:      {metrics['sortino']:+.2f}")
    print(f"  Max Drawdown:       {metrics['max_drawdown']:.1f}%")
    print(f"  Win Rate:           {metrics['win_rate']:.1f}%")
    print(f"  Avg Win:            {metrics['avg_win']:+.2f}%")
    print(f"  Avg Loss:           {metrics['avg_loss']:+.2f}%")
    print(f"  Profit Factor:      {metrics['profit_factor']:.2f}")
    print(f"  Max Consec Losses:  {metrics['max_consec_losses']}")
    print(f"")
    print(f"  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        count, pct, avg, total = metrics["exit_detail"][reason]
        if count > 0:
            print(f"    {reason:15s}: {count:>4,d} ({pct:>5.1f}%)  "
                  f"avg={avg:>+6.2f}%  total={total:>+8.1f}%")

    # ========================================================================
    # COMPARISON TABLE
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  COMPARISON: BB vs Spring vs Combined")
    print(f"{'='*70}")

    bb_m = result_bb.metrics
    sp_m = result_spring.metrics

    # Compute max consecutive losses for BB and Spring
    bb_pnls = [t.pnl_pct for t in result_bb.trades]
    sp_pnls = [t.pnl_pct for t in result_spring.trades]
    bb_max_consec = 0
    consec = 0
    for p in bb_pnls:
        if p <= 0: consec += 1; bb_max_consec = max(bb_max_consec, consec)
        else: consec = 0
    sp_max_consec = 0
    consec = 0
    for p in sp_pnls:
        if p <= 0: consec += 1; sp_max_consec = max(sp_max_consec, consec)
        else: consec = 0

    print(f"\n  {'Metric':25s} {'BB Breakout':>12s} {'Spring':>12s} {'Combined':>12s}")
    print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*12}")
    print(f"  {'Trades':25s} {bb_m.total_trades:>12,d} {sp_m.total_trades:>12,d} {metrics['total_trades']:>12,d}")
    print(f"  {'Compound Return %':25s} {bb_m.total_return_pct:>+11.1f}% {sp_m.total_return_pct:>+11.1f}% {metrics['compound_return']:>+11.1f}%")
    print(f"  {'Linear Sum %':25s} {sum(t.pnl_pct for t in result_bb.trades):>+11.1f}% {sum(t.pnl_pct for t in result_spring.trades):>+11.1f}% {metrics['linear_sum']:>+11.1f}%")
    print(f"  {'Annualized Return %':25s} {bb_m.annualized_return_pct:>+11.1f}% {sp_m.annualized_return_pct:>+11.1f}% {metrics['annualized_return']:>+11.1f}%")
    print(f"  {'Sharpe Ratio':25s} {bb_m.sharpe_ratio:>+11.2f}  {sp_m.sharpe_ratio:>+11.2f}  {metrics['sharpe']:>+11.2f}")
    print(f"  {'Sortino Ratio':25s} {bb_m.sortino_ratio:>+11.2f}  {sp_m.sortino_ratio:>+11.2f}  {metrics['sortino']:>+11.2f}")
    print(f"  {'Max Drawdown %':25s} {bb_m.max_drawdown_pct:>11.1f}% {sp_m.max_drawdown_pct:>11.1f}% {metrics['max_drawdown']:>11.1f}%")
    print(f"  {'Win Rate %':25s} {bb_m.win_rate_pct:>11.1f}% {sp_m.win_rate_pct:>11.1f}% {metrics['win_rate']:>11.1f}%")
    print(f"  {'Avg Win %':25s} {bb_m.avg_win_pct:>+11.2f}% {sp_m.avg_win_pct:>+11.2f}% {metrics['avg_win']:>+11.2f}%")
    print(f"  {'Avg Loss %':25s} {bb_m.avg_loss_pct:>+11.2f}% {sp_m.avg_loss_pct:>+11.2f}% {metrics['avg_loss']:>+11.2f}%")
    print(f"  {'Profit Factor':25s} {bb_m.profit_factor:>11.2f}  {sp_m.profit_factor:>11.2f}  {metrics['profit_factor']:>11.2f}")
    print(f"  {'Max Consec Losses':25s} {bb_max_consec:>12,d} {sp_max_consec:>12,d} {metrics['max_consec_losses']:>12,d}")

    # ========================================================================
    # EXIT DETAILS PER COMPONENT
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  EXIT BREAKDOWN PER COMPONENT")
    print(f"{'='*70}")

    for label, trades, engine_result in [
        ("BB Breakout", result_bb.trades, result_bb),
        ("Spring Reversal", result_spring.trades, result_spring),
    ]:
        exit_counter = Counter(t.exit_reason for t in trades)
        print(f"\n  {label}:")
        for reason in ["take_profit", "stop_loss", "time_exit"]:
            subset = [t for t in trades if t.exit_reason == reason]
            count = len(subset)
            pct = count / len(trades) * 100 if trades else 0
            avg = np.mean([t.pnl_pct for t in subset]) if subset else 0
            total = sum(t.pnl_pct for t in subset)
            print(f"    {reason:15s}: {count:>4d} ({pct:>5.1f}%)  "
                  f"avg={avg:>+6.2f}%  total={total:>+8.1f}%")

    # ========================================================================
    # WALK-FORWARD VALIDATION
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD VALIDATION")
    print(f"{'='*70}")

    # BB Walk-Forward
    print(f"\n  BB Breakout standalone:")
    bb_wf_splits = []
    n = len(df_okx)
    slot = n // 9  # 7 splits + 2
    for s in range(7):
        start = n - (7 - s + 1) * slot
        end = min(n, start + slot)
        oos_df = df_okx.iloc[start:end]
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(oos_df, bb_strategy, symbol="BTC/USDT",
                           stop_loss_pct=bb_exit["stop_pct"],
                           take_profit_pct=bb_exit["target_pct"],
                           max_hold_bars=bb_exit["hold_hours"])
        bb_sum = sum(t.pnl_pct for t in result.trades)
        status = "✅" if bb_sum > 0 else "❌"
        print(f"    Split {s+1}: {oos_df.index[0].strftime('%Y-%m')}→{oos_df.index[-1].strftime('%Y-%m')}  "
              f"trades={result.metrics.total_trades}  sum={bb_sum:+.1f}%  "
              f"sharpe={result.metrics.sharpe_ratio:+.2f}  {status}")
        bb_wf_splits.append(bb_sum > 0)

    bb_wf_profitable = sum(bb_wf_splits)

    # Spring Walk-Forward
    print(f"\n  Spring filtered standalone:")
    spring_wf_splits = []
    for s in range(7):
        start = n - (7 - s + 1) * slot
        end = min(n, start + slot)
        oos_df = df_okx.iloc[start:end]
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(oos_df, spring_strategy, symbol="BTC/USDT",
                           stop_loss_pct=spring_exit["stop_pct"],
                           take_profit_pct=spring_exit["target_pct"],
                           max_hold_bars=spring_exit["hold_hours"])
        sp_sum = sum(t.pnl_pct for t in result.trades)
        status = "✅" if sp_sum > 0 else "❌"
        print(f"    Split {s+1}: {oos_df.index[0].strftime('%Y-%m')}→{oos_df.index[-1].strftime('%Y-%m')}  "
              f"trades={result.metrics.total_trades}  sum={sp_sum:+.1f}%  "
              f"sharpe={result.metrics.sharpe_ratio:+.2f}  {status}")
        spring_wf_splits.append(sp_sum > 0)

    sp_wf_profitable = sum(spring_wf_splits)

    # Combined Walk-Forward
    wf_results, wf_profitable, wf_mean_sharpe, wf_total_sum = walk_forward_combined(
        df_okx, bb_strategy, spring_strategy, bb_exit, spring_exit,
        n_splits=7, label="OKX Combined"
    )

    print(f"\n  Walk-Forward Summary:")
    print(f"    BB Breakout:       {bb_wf_profitable}/7 OOS profitable")
    print(f"    Spring filtered:   {sp_wf_profitable}/7 OOS profitable")
    print(f"    Combined:          {wf_profitable}/7 OOS profitable")

    # ========================================================================
    # BINANCE CROSS-VALIDATION
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  BINANCE CROSS-VALIDATION")
    print(f"{'='*70}")

    engine_bb_bn = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_bb_bn = engine_bb_bn.run(
        df_binance, bb_strategy,
        symbol="BTC/USDT",
        stop_loss_pct=bb_exit["stop_pct"],
        take_profit_pct=bb_exit["target_pct"],
        max_hold_bars=bb_exit["hold_hours"],
    )

    engine_sp_bn = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_sp_bn = engine_sp_bn.run(
        df_binance, spring_strategy,
        symbol="BTC/USDT",
        stop_loss_pct=spring_exit["stop_pct"],
        take_profit_pct=spring_exit["target_pct"],
        max_hold_bars=spring_exit["hold_hours"],
    )

    combined_bn = result_bb_bn.trades + result_sp_bn.trades
    metrics_bn, _, _ = compute_combined_metrics(combined_bn, df_binance)

    print(f"\n  {'Metric':25s} {'OKX':>12s} {'Binance':>12s}")
    print(f"  {'-'*25} {'-'*12} {'-'*12}")
    print(f"  {'Trades':25s} {metrics['total_trades']:>12,d} {metrics_bn['total_trades']:>12,d}")
    print(f"  {'Compound Return %':25s} {metrics['compound_return']:>+11.1f}% {metrics_bn['compound_return']:>+11.1f}%")
    print(f"  {'Linear Sum %':25s} {metrics['linear_sum']:>+11.1f}% {metrics_bn['linear_sum']:>+11.1f}%")
    print(f"  {'Sharpe Ratio':25s} {metrics['sharpe']:>+11.2f}  {metrics_bn['sharpe']:>+11.2f}")
    print(f"  {'Max Drawdown %':25s} {metrics['max_drawdown']:>11.1f}% {metrics_bn['max_drawdown']:>11.1f}%")
    print(f"  {'Win Rate %':25s} {metrics['win_rate']:>11.1f}% {metrics_bn['win_rate']:>11.1f}%")
    print(f"  {'Profit Factor':25s} {metrics['profit_factor']:>11.2f}  {metrics_bn['profit_factor']:>11.2f}")

    # ========================================================================
    # TRADE CORRELATION ANALYSIS
    # ========================================================================

    print(f"\n{'='*70}")
    print(f"  TRADE CORRELATION ANALYSIS")
    print(f"{'='*70}")

    # Compare equity curve growth from BB vs Spring components
    # Group trades by month and compare
    bb_trades = result_bb.trades
    sp_trades = result_spring.trades

    # Monthly PnL for each component
    def monthly_pnl(trades):
        monthly = {}
        for t in trades:
            dt = pd.Timestamp(t.exit_time, unit="ms")
            key = f"{dt.year}-{dt.month:02d}"
            monthly[key] = monthly.get(key, 0.0) + t.pnl_pct
        return monthly

    bb_monthly = monthly_pnl(bb_trades)
    sp_monthly = monthly_pnl(sp_trades)

    all_months = sorted(set(bb_monthly.keys()) | set(sp_monthly.keys()))
    bb_vals = [bb_monthly.get(m, 0.0) for m in all_months]
    sp_vals = [sp_monthly.get(m, 0.0) for m in all_months]

    if len(bb_vals) > 1 and len(sp_vals) > 1:
        corr = np.corrcoef(bb_vals, sp_vals)[0, 1]
        print(f"  Monthly PnL correlation (BB vs Spring): {corr:+.3f}")
        if abs(corr) < 0.3:
            print(f"  → Low correlation — strong diversification benefit")
        elif abs(corr) < 0.6:
            print(f"  → Moderate correlation — moderate diversification benefit")
        else:
            print(f"  → High correlation — limited diversification benefit")

    # Count months where both positive, both negative, divergent
    both_pos = sum(1 for b, s in zip(bb_vals, sp_vals) if b > 0 and s > 0)
    both_neg = sum(1 for b, s in zip(bb_vals, sp_vals) if b < 0 and s < 0)
    bb_pos_sp_neg = sum(1 for b, s in zip(bb_vals, sp_vals) if b > 0 and s < 0)
    bb_neg_sp_pos = sum(1 for b, s in zip(bb_vals, sp_vals) if b < 0 and s > 0)
    non_zero = both_pos + both_neg + bb_pos_sp_neg + bb_neg_sp_pos

    if non_zero > 0:
        print(f"  Monthly regime breakdown ({non_zero} active months):")
        print(f"    Both positive:      {both_pos:>3d} ({both_pos/non_zero*100:.0f}%)")
        print(f"    Both negative:      {both_neg:>3d} ({both_neg/non_zero*100:.0f}%)")
        print(f"    BB+ / Spring-:      {bb_pos_sp_neg:>3d} ({bb_pos_sp_neg/non_zero*100:.0f}%)")
        print(f"    BB- / Spring+:      {bb_neg_sp_pos:>3d} ({bb_neg_sp_pos/non_zero*100:.0f}%)")

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
