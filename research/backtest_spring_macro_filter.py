"""
Spring Reversal — Macro Regime Filter Research
===============================================

Tests whether a 200-day return filter eliminates the consistently negative
walk-forward split during bear markets. The Spring strategy's #1 limitation
is the 2022 bear market split — every configuration (baseline, vol-adaptive,
MTF) has a negative split there.

The regime analysis (research_regime_analysis_v1.md) found:
- Bear (<-20% 200d): Sharpe +0.77 (unfiltered) — but with SMA200 filter,
  these are bear market rallies that fail
- Bull (50-200%): Sharpe -1.80 — TOXIC (breakdowns are noise in uptrends)
- Strong bull (>200%): Sharpe -1.77, 60% stop rate — TOXIC

Hypothesis: A 200-day return filter that avoids both deep bear markets
(200d_ret < threshold) and extreme bull markets (200d_ret > threshold)
will eliminate the negative walk-forward splits.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.signals import (
    spring_reversal_signal, sma, bollinger_bands,
)
from cryptoquant.strategy.base import Strategy


# ============================================================================
# Custom strategy with 200-day return macro filter
# ============================================================================

class SpringMacroStrategy(Strategy):
    """Spring Reversal with 200-day return macro regime filter."""

    timeframe = "1h"
    min_bars = 300
    version = "macro-research-1.0"

    DEFAULT_PARAMS = {
        # Signal generation
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
        # Exit params
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_hours": 24,
        "commission": 0.0005,
        # 1h filters
        "sma200_filter": True,
        "bb_filter": True,
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_low": 0.15,   # expanded from vol-adaptive research
        "bb_high": 0.65,
        # Macro filter
        "macro_filter_enabled": False,
        "macro_lookback_days": 200,
        "macro_bear_threshold": -20.0,  # avoid when 200d return < this (%)
        "macro_bull_threshold": 200.0,  # avoid when 200d return > this (%)
    }

    @property
    def name(self) -> str:
        parts = ["SpringMacro"]
        if self.params.get("macro_filter_enabled"):
            bear = self.params["macro_bear_threshold"]
            bull = self.params["macro_bull_threshold"]
            parts.append(f"M{bear:+.0f}B{bull:+.0f}")
        return "_".join(parts)

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        # Core Spring signal
        signal = spring_reversal_signal(
            df,
            lookback=self.params["lookback"],
            vol_mult=self.params["vol_mult"],
            close_pct=self.params["close_pct"],
        )

        # SMA200 filter
        if self.params.get("sma200_filter", True):
            sma200 = sma(df["close"], 200)
            signal = signal & (df["close"] > sma200)

        # BB %B filter
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

        # Macro regime filter: 200-day return
        if self.params.get("macro_filter_enabled", False):
            lookback = self.params["macro_lookback_days"] * 24  # convert days to 1h bars
            ret_200d = df["close"].pct_change(lookback) * 100
            bear_thresh = self.params["macro_bear_threshold"]
            bull_thresh = self.params["macro_bull_threshold"]

            # Allow only when 200d return is between thresholds
            macro_ok = (ret_200d >= bear_thresh) & (ret_200d <= bull_thresh)
            signal = signal & macro_ok

        return signal.astype(int)


# ============================================================================
# Walk-Forward Backtest
# ============================================================================

def walk_forward(
    df, strategy_cls, params, stop_pct, target_pct, hold_hours,
    n_splits=7, exchange="okx"
):
    """Run walk-forward backtest with given strategy."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)

        if end - start < params.get("min_bars", 300) + 200:
            continue

        split_df = df.iloc[start:end].copy()
        strategy = strategy_cls(params=params.copy())
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            split_df, strategy,
            symbol="BTC/USDT",
            stop_loss_pct=stop_pct,
            take_profit_pct=target_pct,
            max_hold_bars=hold_hours,
        )

        period_start = split_df.index[0].strftime("%Y-%m")
        period_end = split_df.index[-1].strftime("%Y-%m")

        results.append({
            "split": s + 1,
            "period": f"{period_start}→{period_end}",
            "trades": result.metrics.total_trades,
            "return_pct": result.metrics.total_return_pct,
            "sharpe": result.metrics.sharpe_ratio,
            "max_dd": result.metrics.max_drawdown_pct,
            "win_rate": result.metrics.win_rate_pct,
            "pf": result.metrics.profit_factor,
            "status": "✅" if result.metrics.sharpe_ratio > 0 else "❌",
        })

    return results


def full_backtest(df, strategy_cls, params, stop_pct, target_pct, hold_hours, label=""):
    """Run full-period backtest and print results."""
    strategy = strategy_cls(params=params.copy())
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    result = engine.run(
        df, strategy,
        symbol="BTC/USDT",
        stop_loss_pct=stop_pct,
        take_profit_pct=target_pct,
        max_hold_bars=hold_hours,
    )

    m = result.metrics
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    # Compute derived metrics
    linear_sum = sum(t.pnl_pct for t in result.trades)
    consec_losses = 0
    max_consec = 0
    for t in result.trades:
        if t.pnl_pct <= 0:
            consec_losses += 1
            max_consec = max(max_consec, consec_losses)
        else:
            consec_losses = 0

    print(f"  Trades:             {m.total_trades}")
    print(f"  Compound Return:    {m.total_return_pct:+.1f}%")
    print(f"  Linear Sum:         {linear_sum:+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"  Max DD Duration:    {m.max_drawdown_days:.0f}d")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.2f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.2f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Max Consec Losses:  {max_consec}")

    # Exit breakdown
    exits = Counter(t.exit_reason for t in result.trades)
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        count = exits.get(reason, 0)
        pct = count / m.total_trades * 100 if m.total_trades else 0
        subset = [t for t in result.trades if t.exit_reason == reason]
        avg_pnl = np.mean([t.pnl_pct for t in subset]) if subset else 0
        total_pnl = sum(t.pnl_pct for t in subset)
        print(f"    {reason:15s}: {count:4d} ({pct:4.1f}%)  avg={avg_pnl:+.2f}%  total={total_pnl:+.1f}%")

    return result


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("  Spring Reversal — Macro Regime Filter Research")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    print("\n[1/4] Loading data...")
    df_okx = store.load("okx", "BTC/USDT", "1h")
    df_bnc = store.load("binance", "BTC/USDT", "1h")
    print(f"  OKX:     {len(df_okx)} bars, {df_okx.index[0]} → {df_okx.index[-1]}")
    print(f"  Binance: {len(df_bnc)} bars, {df_bnc.index[0]} → {df_bnc.index[-1]}")

    # Baseline params
    base_params = {
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_hours": 24,
        "commission": 0.0005,
        "sma200_filter": True,
        "bb_filter": True,
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_low": 0.15,
        "bb_high": 0.65,
        "macro_filter_enabled": False,
    }

    stop_pct = 3.0
    target_pct = 2.5
    hold_hours = 24

    # ========================================================================
    # Experiment 1: Baseline (no macro filter)
    # ========================================================================
    print("\n[2/4] Running baselines and macro filter variants on OKX...")

    baseline_result = full_backtest(
        df_okx, SpringMacroStrategy, base_params,
        stop_pct, target_pct, hold_hours,
        "BASELINE: Spring filtered (SMA200 + BB 0.15-0.65), no macro filter"
    )

    wf_baseline = walk_forward(
        df_okx, SpringMacroStrategy, base_params,
        stop_pct, target_pct, hold_hours, n_splits=7
    )

    # ========================================================================
    # Experiment 2: Macro filter variants
    # ========================================================================

    # Test different macro filter configurations
    # Rationale from regime analysis:
    # - Bear (<-20% 200d): unfiltered Sharpe +0.77, but with SMA200 filter these
    #   are bear market rallies that fail → filter out
    # - Bull (50-200%): Sharpe -1.80 → TOXIC → filter out
    # - Strong bull (>200%): Sharpe -1.77, 60% stop rate → TOXIC → filter out

    macro_variants = [
        # (bear_thresh, bull_thresh, label)
        (-30.0, 999.0, "Bear filter only (<-30%)"),     # only avoid severe bear
        (-20.0, 999.0, "Bear filter only (<-20%)"),     # avoid bear markets
        (-10.0, 999.0, "Bear filter only (<-10%)"),     # avoid weak bear too
        (0.0, 999.0, "Bear filter only (<0%)"),          # avoid all down trends
        (-20.0, 200.0, "Bear + Bull filter (-20% to 200%)"),  # avoid both extremes
        (-20.0, 150.0, "Bear + Bull filter (-20% to 150%)"),
        (-20.0, 100.0, "Bear + Bull filter (-20% to 100%)"),
        (-20.0, 50.0, "Bear + Bull filter (-20% to 50%)"),
        (-30.0, 200.0, "Bear + Bull filter (-30% to 200%)"),
        (-30.0, 150.0, "Bear + Bull filter (-30% to 150%)"),
        (-40.0, 150.0, "Bear + Bull filter (-40% to 150%)"),
    ]

    all_results = []

    for bear_thresh, bull_thresh, label in macro_variants:
        params = base_params.copy()
        params["macro_filter_enabled"] = True
        params["macro_bear_threshold"] = bear_thresh
        params["macro_bull_threshold"] = bull_thresh

        result = full_backtest(
            df_okx, SpringMacroStrategy, params,
            stop_pct, target_pct, hold_hours,
            f"MACRO: {label}"
        )

        wf = walk_forward(
            df_okx, SpringMacroStrategy, params,
            stop_pct, target_pct, hold_hours, n_splits=7
        )

        all_results.append({
            "label": label,
            "bear_thresh": bear_thresh,
            "bull_thresh": bull_thresh,
            "trades": result.metrics.total_trades,
            "return": result.metrics.total_return_pct,
            "sharpe": result.metrics.sharpe_ratio,
            "max_dd": result.metrics.max_drawdown_pct,
            "win_rate": result.metrics.win_rate_pct,
            "pf": result.metrics.profit_factor,
            "wf_profitable": sum(1 for r in wf if r["sharpe"] > 0),
            "wf_total": len(wf),
            "wf_mean_sharpe": np.mean([r["sharpe"] for r in wf]),
            "wf_details": wf,
        })

    # ========================================================================
    # Print comparison table
    # ========================================================================
    print("\n\n" + "=" * 100)
    print("  COMPARISON TABLE — Full Backtest (OKX BTC/USDT 1h, 2019-2026)")
    print("=" * 100)
    header = f"  {'Config':<40s} {'Trades':>7s} {'Return':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>5s} {'WF':>5s} {'MeanOOS':>7s}"
    print(header)
    print("  " + "-" * 96)

    # Baseline
    m = baseline_result.metrics
    print(f"  {'BASELINE (no macro filter)':<40s} {m.total_trades:7d} {m.total_return_pct:+8.1f}% {m.sharpe_ratio:+7.2f} {m.max_drawdown_pct:+7.1f}% {m.win_rate_pct:+6.1f}% {m.profit_factor:+5.2f} {wf_baseline[0]['status']} {np.mean([r['sharpe'] for r in wf_baseline]):+7.2f}")

    for r in all_results:
        print(f"  {r['label']:<40s} {r['trades']:7d} {r['return']:+8.1f}% {r['sharpe']:+7.2f} {r['max_dd']:+7.1f}% {r['win_rate']:+6.1f}% {r['pf']:+5.2f} {r['wf_profitable']}/{r['wf_total']} {r['wf_mean_sharpe']:+7.2f}")

    # ========================================================================
    # Print Walk-Forward Detail for Best Variant
    # ========================================================================
    print("\n\n" + "=" * 100)
    print("  WALK-FORWARD DETAIL — Baseline vs Best Macro Filter")
    print("=" * 100)

    # Find best variant by WF mean Sharpe
    best = max(all_results, key=lambda x: x["wf_mean_sharpe"])
    print(f"\n  Best variant: {best['label']}")
    print(f"  WF: {best['wf_profitable']}/{best['wf_total']} profitable, Mean OOS Sharpe: {best['wf_mean_sharpe']:+.2f}")

    print(f"\n  {'Split':>6s} {'Period':<22s} {'Base Trades':>12s} {'Base Sharpe':>12s} {'Macro Trades':>13s} {'Macro Sharpe':>12s}")
    print("  " + "-" * 78)

    for i, (b, mf) in enumerate(zip(wf_baseline, best["wf_details"])):
        print(f"  {b['split']:6d} {b['period']:<22s} {b['trades']:12d} {b['sharpe']:+12.2f} {mf['trades']:13d} {mf['sharpe']:+12.2f}")

    print(f"\n  Baseline WF: {sum(1 for r in wf_baseline if r['sharpe']>0)}/{len(wf_baseline)} profitable, Mean OOS Sharpe: {np.mean([r['sharpe'] for r in wf_baseline]):+.2f}")
    print(f"  Macro WF:    {best['wf_profitable']}/{best['wf_total']} profitable, Mean OOS Sharpe: {best['wf_mean_sharpe']:+.2f}")

    # ========================================================================
    # Binance Cross-Validation (baseline + best variant)
    # ========================================================================
    print("\n\n" + "=" * 70)
    print("  BINANCE CROSS-VALIDATION")
    print("=" * 70)

    print("\n  BASELINE (no macro filter) on Binance:")
    full_backtest(
        df_bnc, SpringMacroStrategy, base_params,
        stop_pct, target_pct, hold_hours,
        "BASELINE"
    )
    wf_bnc_baseline = walk_forward(
        df_bnc, SpringMacroStrategy, base_params,
        stop_pct, target_pct, hold_hours, n_splits=7, exchange="binance"
    )

    best_params = base_params.copy()
    best_params["macro_filter_enabled"] = True
    best_params["macro_bear_threshold"] = best["bear_thresh"]
    best_params["macro_bull_threshold"] = best["bull_thresh"]

    print(f"\n  MACRO ({best['label']}) on Binance:")
    full_backtest(
        df_bnc, SpringMacroStrategy, best_params,
        stop_pct, target_pct, hold_hours,
        f"MACRO ({best['label']})"
    )
    wf_bnc_macro = walk_forward(
        df_bnc, SpringMacroStrategy, best_params,
        stop_pct, target_pct, hold_hours, n_splits=7, exchange="binance"
    )

    print(f"\n  Binance WF Baseline: {sum(1 for r in wf_bnc_baseline if r['sharpe']>0)}/{len(wf_bnc_baseline)} profitable, Mean OOS Sharpe: {np.mean([r['sharpe'] for r in wf_bnc_baseline]):+.2f}")
    print(f"  Binance WF Macro:    {sum(1 for r in wf_bnc_macro if r['sharpe']>0)}/{len(wf_bnc_macro)} profitable, Mean OOS Sharpe: {np.mean([r['sharpe'] for r in wf_bnc_macro]):+.2f}")

    # ========================================================================
    # Per-Regime Breakdown for Best Variant
    # ========================================================================
    print("\n\n" + "=" * 70)
    print("  PER-REGIME BREAKDOWN — Best Macro Filter (OKX)")
    print("=" * 70)

    # Run with macro filter and tag trades by 200d return regime
    strategy = SpringMacroStrategy(params=best_params)
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    result = engine.run(
        df_okx, strategy,
        symbol="BTC/USDT",
        stop_loss_pct=stop_pct,
        take_profit_pct=target_pct,
        max_hold_bars=hold_hours,
    )

    # Tag each trade with 200d return at entry
    # The entry_time is in Unix ms, df_okx index is DatetimeIndex
    ret_200d = df_okx["close"].pct_change(200 * 24) * 100
    trade_macro_rets = []
    for t in result.trades:
        entry_ts = pd.Timestamp(t.entry_time, unit="ms")
        if entry_ts in ret_200d.index:
            val = ret_200d.loc[entry_ts]
            if hasattr(val, 'iloc'):
                val = val.iloc[0] if len(val) > 0 else np.nan
            trade_macro_rets.append(float(val) if not (isinstance(val, float) and np.isnan(val)) else np.nan)
        else:
            # Find nearest timestamp
            idx = ret_200d.index.get_indexer([entry_ts], method="nearest")[0]
            if idx >= 0:
                trade_macro_rets.append(float(ret_200d.iloc[idx]))
            else:
                trade_macro_rets.append(np.nan)

    regimes = [
        ("Deep Bear (<-40%)", lambda x: x < -40),
        ("Bear (-40% to -20%)", lambda x: -40 <= x < -20),
        ("Weak Bear (-20% to 0%)", lambda x: -20 <= x < 0),
        ("Weak Bull (0% to 50%)", lambda x: 0 <= x < 50),
        ("Bull (50% to 150%)", lambda x: 50 <= x < 150),
        ("Strong Bull (150% to 200%)", lambda x: 150 <= x < 200),
        ("Extreme Bull (>200%)", lambda x: x >= 200),
    ]

    print(f"\n  {'Regime':<30s} {'Trades':>7s} {'Sum PnL':>10s} {'Avg PnL':>10s} {'WinRate':>8s} {'StopRate':>9s}")
    print("  " + "-" * 78)
    for name, cond in regimes:
        subset = [(t, mr) for t, mr in zip(result.trades, trade_macro_rets) if not np.isnan(mr) and cond(mr)]
        if subset:
            total_pnl = sum(pair[0].pnl_pct for pair in subset)
            avg_pnl = np.mean([pair[0].pnl_pct for pair in subset])
            wr = sum(1 for pair in subset if pair[0].pnl_pct > 0) / len(subset) * 100
            sr = sum(1 for pair in subset if pair[0].exit_reason == "stop_loss") / len(subset) * 100
            print(f"  {name:<30s} {len(subset):7d} {total_pnl:+10.1f}% {avg_pnl:+10.2f}% {wr:+8.1f}% {sr:+9.1f}%")
        else:
            print(f"  {name:<30s} {0:7d} {'--':>10s} {'--':>10s} {'--':>8s} {'--':>9s}")

    print("\n" + "=" * 70)
    print("  Research complete. See docs/research/spring/ for documentation.")
    print("=" * 70)


if __name__ == "__main__":
    main()
