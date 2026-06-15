"""
BB Breakout + Spring Reversal — ADX Regime Threshold Optimization
==================================================================

The regime allocation v1 research (80/20 scheme) used ADX thresholds:
  - Trending: ADX > 25
  - Ranging:  ADX ≤ 20
  - Neutral:  20 < ADX ≤ 25

These were chosen by convention, not data-driven optimization.

Hypothesis: Sweeping trending threshold (22-32) and ranging threshold (12-24)
with walk-forward validation will identify thresholds that further improve
Sharpe, reduce MaxDD, and improve WF robustness over the default (25/20).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.types import Trade
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, bollinger_bands, adx as adx_func,
)


# ============================================================================
# Strategy Classes
# ============================================================================

class BBUpperBreakoutNoSMA(Strategy):
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"
    DEFAULT_PARAMS = {"bb_period": 50, "bb_std": 2.5}

    @property
    def name(self) -> str:
        return "BB_Upper_Breakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        bb = bollinger_bands(df, period=50, std=2.5)
        signal = df["close"] > bb["upper"]
        return signal.astype(int)


class SpringFiltered(Strategy):
    timeframe = "1h"
    min_bars = 250
    version = "2.0.0"
    DEFAULT_PARAMS = {"lookback": 20, "vol_mult": 1.5, "close_pct": 0.5}

    @property
    def name(self) -> str:
        return "Spring_Filtered"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        opens, highs, lows, closes, volumes = df["open"], df["high"], df["low"], df["close"], df["volume"]
        rolling_low = lows.rolling(20).min().shift(1)
        new_low = lows < rolling_low
        bullish_close = closes > opens
        bar_range = highs - lows
        close_position = (closes - lows) / bar_range.replace(0, np.nan)
        close_near_high = close_position > 0.5
        avg_vol = volumes.rolling(20).mean().shift(1)
        high_volume = volumes > (1.5 * avg_vol)
        base = new_low & bullish_close & close_near_high & high_volume
        sma200 = sma(closes, 200)
        bb = bollinger_bands(df, 20, 2.0)
        bb_filter = (bb["pct_b"] >= 0.2) & (bb["pct_b"] < 0.6)
        sma_filter = closes > sma200
        filtered = base & bb_filter & sma_filter
        return filtered.astype(int)


# ============================================================================
# ADX Regime Classification (parameterized)
# ============================================================================

def classify_regime_adx(df: pd.DataFrame, trending_thresh: float, ranging_thresh: float) -> pd.Series:
    """Classify each bar into trending/ranging/neutral based on ADX."""
    adx_series = adx_func(df, period=14)
    adx_vals = adx_series["adx"]

    def _classify(adx_val):
        if pd.isna(adx_val):
            return "neutral"
        if adx_val > trending_thresh:
            return "trending"
        elif adx_val <= ranging_thresh:
            return "ranging"
        else:
            return "neutral"

    return adx_vals.apply(_classify)


# ============================================================================
# Regime-Based Combined Metrics (parameterized)
# ============================================================================

def compute_regime_combined_metrics(
    bb_trades: list,
    spring_trades: list,
    df: pd.DataFrame,
    trending_thresh: float,
    ranging_thresh: float,
    initial_capital: float = 10_000.0,
):
    """80/20 regime-based allocation with parameterized thresholds."""
    regime = classify_regime_adx(df, trending_thresh, ranging_thresh)

    def get_weight(trade, strategy_type: str) -> float:
        entry_ts = pd.Timestamp(trade.entry_time, unit="ms")
        idx = df.index.get_indexer([entry_ts], method="ffill")[0]
        if idx < 0 or idx >= len(df):
            return 0.5

        reg = regime.iloc[idx]

        if reg == "trending":
            return 0.8 if strategy_type == "bb" else 0.2
        elif reg == "ranging":
            return 0.2 if strategy_type == "bb" else 0.8
        else:  # neutral
            return 0.5

    all_trades = []
    for t in bb_trades:
        w = get_weight(t, "bb")
        all_trades.append({
            "exit_time": t.exit_time,
            "pnl_pct": t.pnl_pct * w,
            "exit_reason": t.exit_reason,
        })
    for t in spring_trades:
        w = get_weight(t, "spring")
        all_trades.append({
            "exit_time": t.exit_time,
            "pnl_pct": t.pnl_pct * w,
            "exit_reason": t.exit_reason,
        })

    sorted_trades = sorted(all_trades, key=lambda t: t["exit_time"])

    # Compound equity
    exit_times = [pd.Timestamp(t["exit_time"], unit="ms") for t in sorted_trades]
    factors = [1.0 + t["pnl_pct"] / 100.0 for t in sorted_trades]

    if not factors:
        return {"total_trades": 0, "sharpe": 0.0, "compound_return": 0.0,
                "max_drawdown": 0.0, "linear_sum": 0.0}, None, None

    equity_jumps = pd.Series(factors, index=exit_times, dtype=float)
    equity_jumps.sort_index(inplace=True)
    cumulative = equity_jumps.cumprod()

    curve = pd.Series(initial_capital, index=df.index, dtype=float)
    for ts, factor in cumulative.items():
        mask = df.index >= ts
        if mask.any():
            curve[mask] = initial_capital * factor

    dd_curve = (curve / curve.cummax() - 1) * 100

    # Sharpe
    daily_returns = curve.resample("1D").last().pct_change().dropna()
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(365))
    else:
        sharpe = 0.0

    nonzero_trades = [t for t in sorted_trades if abs(t["pnl_pct"]) > 1e-10]
    final_equity = curve.iloc[-1]
    compound_return = (final_equity / initial_capital - 1) * 100
    linear_sum = sum(t["pnl_pct"] for t in nonzero_trades)

    return {
        "total_trades": len(nonzero_trades),
        "sharpe": sharpe,
        "compound_return": compound_return,
        "linear_sum": linear_sum,
        "max_drawdown": dd_curve.min(),
    }, curve, dd_curve


# ============================================================================
# Walk-Forward Sweep
# ============================================================================

def walk_forward_sweep(
    df: pd.DataFrame,
    bb_strategy: Strategy,
    spring_strategy: Strategy,
    bb_exit: dict,
    spring_exit: dict,
    threshold_combos: list[tuple[float, float]],
    n_splits: int = 7,
):
    """Run walk-forward for all threshold combinations."""
    n = len(df)
    slot = n // (n_splits + 2)

    # Pre-compute individual backtest results for all splits
    # (BB and Spring trades don't depend on thresholds — only allocation does)
    split_bb_trades = []
    split_sp_trades = []
    split_dfs = []

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        oos_df = df.iloc[start:end]

        engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_bb = engine_bb.run(
            oos_df, bb_strategy, symbol="BTC/USDT",
            stop_loss_pct=bb_exit["stop_pct"],
            take_profit_pct=bb_exit["target_pct"],
            max_hold_bars=bb_exit["hold_hours"],
        )

        engine_sp = BacktestEngine(commission=0.0005, slippage=0.0005)
        result_sp = engine_sp.run(
            oos_df, spring_strategy, symbol="BTC/USDT",
            stop_loss_pct=spring_exit["stop_pct"],
            take_profit_pct=spring_exit["target_pct"],
            max_hold_bars=spring_exit["hold_hours"],
        )

        split_bb_trades.append(result_bb.trades)
        split_sp_trades.append(result_sp.trades)
        split_dfs.append(oos_df)

    # Now evaluate all threshold combos against these pre-computed trades
    results = {}
    for t_thresh, r_thresh in threshold_combos:
        combo_key = f"t{t_thresh:.0f}_r{r_thresh:.0f}"
        splits = []
        for s in range(n_splits):
            metrics, _, _ = compute_regime_combined_metrics(
                split_bb_trades[s], split_sp_trades[s], split_dfs[s],
                trending_thresh=t_thresh, ranging_thresh=r_thresh,
            )
            splits.append({
                "split": s + 1,
                "period": f"{split_dfs[s].index[0].strftime('%Y-%m')}→{split_dfs[s].index[-1].strftime('%Y-%m')}",
                "sum": metrics["linear_sum"],
                "sharpe": metrics["sharpe"],
                "trades": metrics["total_trades"],
            })

        profitable = sum(1 for sp in splits if sp["sum"] > 0)
        mean_sharpe = np.mean([sp["sharpe"] for sp in splits])
        total_sum = sum(sp["sum"] for sp in splits)
        split7_sum = splits[-1]["sum"]
        split7_sharpe = splits[-1]["sharpe"]

        results[combo_key] = {
            "t_thresh": t_thresh,
            "r_thresh": r_thresh,
            "splits": splits,
            "profitable": profitable,
            "mean_sharpe": mean_sharpe,
            "total_sum": total_sum,
            "split7_sum": split7_sum,
            "split7_sharpe": split7_sharpe,
        }

    return results


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("ADX REGIME THRESHOLD OPTIMIZATION — WALK-FORWARD SWEEP")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    df_okx = store.load("okx", "BTC/USDT", "1h")
    print(f"\nOKX: {len(df_okx):,} bars, {df_okx.index[0]} to {df_okx.index[-1]}")

    # Strategy configs
    bb_strategy = BBUpperBreakoutNoSMA()
    spring_strategy = SpringFiltered()
    bb_exit = {"stop_pct": 1.2, "target_pct": 4.0, "hold_hours": 10}
    spring_exit = {"stop_pct": 3.0, "target_pct": 3.0, "hold_hours": 16}

    # ========================================================================
    # THRESHOLD COMBINATIONS TO TEST
    # ========================================================================
    trending_candidates = [20, 22, 25, 28, 30, 32]
    ranging_candidates = [12, 15, 18, 20, 22, 24]

    combos = []
    for t in trending_candidates:
        for r in ranging_candidates:
            if t - r >= 3:  # must have neutral zone
                combos.append((float(t), float(r)))

    print(f"\nTesting {len(combos)} threshold combinations...")
    print(f"  Trending thresholds: {trending_candidates}")
    print(f"  Ranging thresholds:  {ranging_candidates}")
    print(f"  Constraint: trending - ranging >= 3 (minimum neutral zone)")

    # ========================================================================
    # WALK-FORWARD SWEEP
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD SWEEP (7 splits)")
    print(f"{'='*70}")

    wf_results = walk_forward_sweep(
        df_okx, bb_strategy, spring_strategy, bb_exit, spring_exit,
        threshold_combos=combos, n_splits=7,
    )

    # ========================================================================
    # SORT AND DISPLAY
    # ========================================================================
    # Sort by mean OOS Sharpe
    sorted_results = sorted(wf_results.items(), key=lambda x: x[1]["mean_sharpe"], reverse=True)

    print(f"\n{'='*70}")
    print(f"  RESULTS — SORTED BY MEAN OOS SHARPE")
    print(f"{'='*70}")
    print(f"\n  {'Rank':5s} {'Combo':10s} {'T/R':10s} {'Mean OOS':>9s} {'Profitable':>11s} {'Total Sum':>10s} {'Split7 Sum':>10s} {'Split7 Sh':>9s}")
    print(f"  {'-'*5} {'-'*10} {'-'*10} {'-'*9} {'-'*11} {'-'*10} {'-'*10} {'-'*9}")

    for rank, (key, r) in enumerate(sorted_results, 1):
        print(f"  {rank:>5d} {key:10s} {r['t_thresh']:>4.0f}/{r['r_thresh']:<4.0f}  "
              f"{r['mean_sharpe']:>+8.2f}  {r['profitable']:>4d}/{len(r['splits']):<6d} "
              f"{r['total_sum']:>+9.1f}% {r['split7_sum']:>+9.1f}% {r['split7_sharpe']:>+8.2f}")

    # ========================================================================
    # BASELINE COMPARISON (t25/r20)
    # ========================================================================
    baseline_key = "t25_r20"
    baseline = wf_results.get(baseline_key)

    print(f"\n{'='*70}")
    print(f"  BASELINE vs BEST COMPARISON")
    print(f"{'='*70}")

    if baseline and sorted_results:
        best_key, best = sorted_results[0]

        print(f"\n  {'Metric':22s} {'Baseline (t25/r20)':>20s} {'Best (' + best_key + ')':>20s} {'Delta':>10s}")
        print(f"  {'-'*22} {'-'*20} {'-'*20} {'-'*10}")
        print(f"  {'Mean OOS Sharpe':22s} {baseline['mean_sharpe']:>+19.2f}  {best['mean_sharpe']:>+19.2f}  {best['mean_sharpe']-baseline['mean_sharpe']:>+9.2f}")
        print(f"  {'OOS Profitable':22s} {str(baseline['profitable']) + '/7':>20s} {str(best['profitable']) + '/7':>20s}")
        print(f"  {'Total OOS Sum %':22s} {baseline['total_sum']:>+19.1f}% {best['total_sum']:>+19.1f}% {best['total_sum']-baseline['total_sum']:>+9.1f}%")
        print(f"  {'Split7 Sum %':22s} {baseline['split7_sum']:>+19.1f}% {best['split7_sum']:>+19.1f}% {best['split7_sum']-baseline['split7_sum']:>+9.1f}%")
        print(f"  {'Split7 Sharpe':22s} {baseline['split7_sharpe']:>+19.2f}  {best['split7_sharpe']:>+19.2f}  {best['split7_sharpe']-baseline['split7_sharpe']:>+9.2f}")

    # ========================================================================
    # FULL BACKTEST FOR TOP 3 COMBOS
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  FULL BACKTEST — TOP 3 THRESHOLD COMBOS (OKX BTC/USDT 1h)")
    print(f"{'='*70}")

    engine_bb = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_bb = engine_bb.run(
        df_okx, bb_strategy, symbol="BTC/USDT",
        stop_loss_pct=bb_exit["stop_pct"],
        take_profit_pct=bb_exit["target_pct"],
        max_hold_bars=bb_exit["hold_hours"],
    )
    engine_sp = BacktestEngine(commission=0.0005, slippage=0.0005)
    result_sp = engine_sp.run(
        df_okx, spring_strategy, symbol="BTC/USDT",
        stop_loss_pct=spring_exit["stop_pct"],
        take_profit_pct=spring_exit["target_pct"],
        max_hold_bars=spring_exit["hold_hours"],
    )

    print(f"\n  BB Breakout:     {result_bb.metrics.total_trades} trades, Sharpe {result_bb.metrics.sharpe_ratio:+.2f}")
    print(f"  Spring Filtered: {result_sp.metrics.total_trades} trades, Sharpe {result_sp.metrics.sharpe_ratio:+.2f}")

    top3_keys = [k for k, _ in sorted_results[:3]]

    for combo_key in top3_keys:
        r = wf_results[combo_key]
        metrics, _, _ = compute_regime_combined_metrics(
            result_bb.trades, result_sp.trades, df_okx,
            trending_thresh=r["t_thresh"], ranging_thresh=r["r_thresh"],
        )
        print(f"\n  {combo_key} (trending >{r['t_thresh']:.0f}, ranging ≤{r['r_thresh']:.0f}):")
        print(f"    Compound Return:  {metrics['compound_return']:>+8.1f}%")
        print(f"    Linear Sum:       {metrics['linear_sum']:>+8.1f}%")
        print(f"    Sharpe Ratio:     {metrics['sharpe']:>+8.2f}")
        print(f"    Max Drawdown:     {metrics['max_drawdown']:>8.1f}%")
        print(f"    Active Trades:    {metrics['total_trades']:>8d}")

    # ========================================================================
    # REGIME DISTRIBUTION ANALYSIS FOR BEST COMBO
    # ========================================================================
    if sorted_results:
        best_key, best = sorted_results[0]
        print(f"\n{'='*70}")
        print(f"  REGIME DISTRIBUTION — BEST COMBO ({best_key})")
        print(f"{'='*70}")

        regime = classify_regime_adx(df_okx, best["t_thresh"], best["r_thresh"])
        counts = regime.value_counts()
        for reg in ["trending", "neutral", "ranging"]:
            c = counts.get(reg, 0)
            pct = c / len(regime) * 100
            print(f"  {reg:12s}: {c:>6,d} bars ({pct:>5.1f}%)")

        # Compare with baseline
        regime_base = classify_regime_adx(df_okx, 25.0, 20.0)
        counts_base = regime_base.value_counts()
        print(f"\n  Regime shift from baseline (t25/r20):")
        for reg in ["trending", "neutral", "ranging"]:
            old = counts_base.get(reg, 0)
            new = counts.get(reg, 0)
            delta = new - old
            old_pct = old / len(regime_base) * 100
            new_pct = new / len(regime) * 100
            print(f"    {reg:12s}: {old_pct:5.1f}% → {new_pct:5.1f}%  ({delta:+,d} bars)")

    # ========================================================================
    # DETAILED SPLIT RESULTS FOR TOP 3
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  DETAILED WALK-FORWARD SPLITS — TOP 3 COMBOS")
    print(f"{'='*70}")

    for rank, (key, r) in enumerate(sorted_results[:3], 1):
        print(f"\n  #{rank}: {key} (t>{r['t_thresh']:.0f}, r≤{r['r_thresh']:.0f})")
        print(f"  {'Split':6s} {'Period':20s} {'Trades':>7s} {'Sum':>8s} {'Sharpe':>8s} {'Status':>6s}")
        print(f"  {'-'*6} {'-'*20} {'-'*7} {'-'*8} {'-'*8} {'-'*6}")
        for sp in r["splits"]:
            status = "✅" if sp["sum"] > 0 else "❌"
            print(f"  {sp['split']:>6d} {sp['period']:20s} {sp['trades']:>7d} {sp['sum']:>+7.1f}% {sp['sharpe']:>+7.2f}  {status:>6s}")
        print(f"  → {r['profitable']}/{len(r['splits'])} OOS profitable | Mean Sharpe: {r['mean_sharpe']:+.2f} | Total Sum: {r['total_sum']:+.1f}%")

    # ========================================================================
    # PARAMETER SENSITIVITY HEATMAP (ASCII)
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  MEAN OOS SHARPE HEATMAP")
    print(f"{'='*70}")
    print(f"\n  Trending →")
    header = "  Ranging ↓  " + "  ".join(f"{t:>4.0f}" for t in trending_candidates)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for r in ranging_candidates:
        row = f"  {r:>8.0f}   "
        for t in trending_candidates:
            key = f"t{t:.0f}_r{r:.0f}"
            if key in wf_results:
                val = wf_results[key]["mean_sharpe"]
                row += f" {val:>+6.2f}"
            else:
                row += "   N/A "
        print(row)

    # ========================================================================
    # SUMMARY
    # ========================================================================
    print(f"\n{'='*70}")
    print(f"  RESEARCH COMPLETE — THRESHOLD SWEEP")
    print(f"{'='*70}")

    if sorted_results:
        best_key, best = sorted_results[0]
        print(f"\n  Best combo: {best_key} (t>{best['t_thresh']:.0f}, r≤{best['r_thresh']:.0f})")
        print(f"  Mean OOS Sharpe: {best['mean_sharpe']:+.2f}")
        print(f"  OOS Profitable: {best['profitable']}/{len(best['splits'])}")
        if baseline_key in wf_results:
            delta_sharpe = best["mean_sharpe"] - wf_results[baseline_key]["mean_sharpe"]
            delta_split7 = best["split7_sum"] - wf_results[baseline_key]["split7_sum"]
            print(f"  vs baseline (t25/r20): ΔSharpe {delta_sharpe:+.2f}, ΔSplit7 {delta_split7:+.1f}%")
        print(f"\n  ALL results written to stdout above.")


if __name__ == "__main__":
    main()
