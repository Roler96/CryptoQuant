"""
Spring Reversal — Multi-Timeframe Confirmation Research
=======================================================

Tests whether higher-timeframe (4h) trend filters improve the Spring
Reversal strategy beyond the existing 1h SMA200 + BB %B filters.

Hypothesis: Spring signals during a 4h uptrend have higher success rates
because the "failed breakdown" is a genuine trap within a larger uptrend,
not a continuation of a larger downtrend.

Variants tested:
  1. Baseline (1h SMA200 + BB 0.2-0.6) — existing best config
  2. 4h close > 4h SMA200
  3. 4h SMA50 > 4h SMA200 (Golden Cross on HTF)
  4. 4h close > 4h SMA50
  5. 4h ADX > 20 (trending HTF)
  6. Combo: 4h SMA50 > SMA200 AND 4h close > 4h SMA50
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.signals import (
    spring_reversal_signal, sma, bollinger_bands, adx as adx_func,
)
from cryptoquant.strategy.base import Strategy


# ============================================================================
# Resample 1h to 4h bars
# ============================================================================

def resample_to_4h(df_1h):
    """Resample 1h OHLCV to 4h bars."""
    df_4h = df_1h.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return df_4h


# ============================================================================
# Custom strategy with 4h confirmation
# ============================================================================

class SpringMTFStrategy(Strategy):
    """Spring Reversal with multi-timeframe confirmation from 4h data."""

    timeframe = "1h"
    min_bars = 300
    version = "mtf-research-1.0"

    DEFAULT_PARAMS = {
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
        "bb_low": 0.2,
        "bb_high": 0.6,
        # Multi-timeframe filters
        "mtf_4h_above_sma200": False,
        "mtf_4h_golden_cross": False,
        "mtf_4h_above_sma50": False,
        "mtf_4h_adx_trending": False,
        "df_4h": None,  # must be injected
    }

    @property
    def name(self) -> str:
        parts = ["SpringReversalMTF"]
        if self.params.get("mtf_4h_above_sma200"):
            parts.append("4h>SMA200")
        if self.params.get("mtf_4h_golden_cross"):
            parts.append("4hGC")
        if self.params.get("mtf_4h_above_sma50"):
            parts.append("4h>SMA50")
        if self.params.get("mtf_4h_adx_trending"):
            parts.append("4hADX>20")
        return "_".join(parts)

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        df_4h = self.params.get("df_4h")
        if df_4h is None:
            raise ValueError("df_4h must be provided in params")

        # Core Spring signal on 1h
        signal = spring_reversal_signal(
            df,
            lookback=self.params["lookback"],
            vol_mult=self.params["vol_mult"],
            close_pct=self.params["close_pct"],
        )

        # 1h SMA200 filter
        if self.params.get("sma200_filter", True):
            sma200_1h = sma(df["close"], 200)
            signal = signal & (df["close"] > sma200_1h)

        # 1h BB %B filter
        if self.params.get("bb_filter", True):
            bb = bollinger_bands(df, self.params["bb_period"], self.params["bb_std"])
            pct_b = bb["pct_b"]
            signal = signal & (
                (pct_b >= self.params["bb_low"])
                & (pct_b < self.params["bb_high"])
            )

        # Multi-timeframe 4h filters — map 4h signals back to 1h timestamps
        # For each 1h bar, find the most recent completed 4h bar
        if any([
            self.params.get("mtf_4h_above_sma200"),
            self.params.get("mtf_4h_golden_cross"),
            self.params.get("mtf_4h_above_sma50"),
            self.params.get("mtf_4h_adx_trending"),
        ]):
            # Compute 4h indicators
            if "sma200_4h" not in df_4h.columns:
                df_4h["sma200_4h"] = sma(df_4h["close"], 200)
                df_4h["sma50_4h"] = sma(df_4h["close"], 50)
                adx_4h = adx_func(df_4h, 14)
                df_4h["adx_4h"] = adx_4h["adx"]
                df_4h["pdi_4h"] = adx_4h["pdi"]
                df_4h["mdi_4h"] = adx_4h["mdi"]

            # Map 4h conditions to 1h timestamps using reindex + ffill
            # Use the 4h bar that closed BEFORE the current 1h bar
            mtf_ok = pd.Series(True, index=df.index)

            if self.params.get("mtf_4h_above_sma200"):
                cond_4h = (df_4h["close"] > df_4h["sma200_4h"]).astype(float)
                cond_1h = cond_4h.reindex(df.index, method="ffill").fillna(0).astype(bool)
                mtf_ok = mtf_ok & cond_1h

            if self.params.get("mtf_4h_golden_cross"):
                cond_4h = (df_4h["sma50_4h"] > df_4h["sma200_4h"]).astype(float)
                cond_1h = cond_4h.reindex(df.index, method="ffill").fillna(0).astype(bool)
                mtf_ok = mtf_ok & cond_1h

            if self.params.get("mtf_4h_above_sma50"):
                cond_4h = (df_4h["close"] > df_4h["sma50_4h"]).astype(float)
                cond_1h = cond_4h.reindex(df.index, method="ffill").fillna(0).astype(bool)
                mtf_ok = mtf_ok & cond_1h

            if self.params.get("mtf_4h_adx_trending"):
                cond_4h = (df_4h["adx_4h"] > 20).astype(float)
                cond_1h = cond_4h.reindex(df.index, method="ffill").fillna(0).astype(bool)
                mtf_ok = mtf_ok & cond_1h

            signal = signal & mtf_ok

        return signal.astype(int)


# ============================================================================
# Walk-forward validation
# ============================================================================

def walk_forward(df, strategy_class, params, n_splits=6, **engine_kwargs):
    """Run walk-forward validation and return split results."""
    n = len(df)
    slot = n // (n_splits + 2)
    splits = []

    for s in range(n_splits):
        start = n - (n_splits - s + 1) * slot
        end = min(n, start + slot)
        split_df = df.iloc[start:end]

        strategy = strategy_class(params=params)
        engine = BacktestEngine(**engine_kwargs)
        try:
            result = engine.run(
                split_df, strategy,
                symbol="BTC/USDT",
                stop_loss_pct=params.get("stop_pct"),
                take_profit_pct=params.get("target_pct"),
                max_hold_bars=params.get("hold_hours"),
            )
            splits.append({
                "start": split_df.index[0],
                "end": split_df.index[-1],
                "trades": result.metrics.total_trades,
                "return": result.metrics.total_return_pct,
                "sharpe": result.metrics.sharpe_ratio,
                "max_dd": result.metrics.max_drawdown_pct,
            })
        except Exception as e:
            splits.append({
                "start": split_df.index[0],
                "end": split_df.index[-1],
                "trades": 0,
                "return": 0,
                "sharpe": 0,
                "max_dd": 0,
                "error": str(e),
            })

    return splits


def print_metrics(result, label=""):
    """Print formatted metrics from BacktestResult."""
    m = result.metrics
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    print(f"  Total Trades:       {m.total_trades}")
    print(f"  Total Return:       {m.total_return_pct:+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:+.1f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.2f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.2f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Avg Hold Hours:     {m.avg_hold_hours:.1f}")

    # Exit breakdown
    reasons = Counter(t.exit_reason for t in result.trades)
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse", "end_of_data"]:
        subset = [t.pnl_pct for t in result.trades if t.exit_reason == reason]
        if subset:
            print(f"    {reason:15s}: {len(subset):4d} ({len(subset)/len(result.trades)*100:5.1f}%)  avg={np.mean(subset):+.2f}%  total={sum(subset):+.1f}%")

    # Max consecutive losses
    pnls = [t.pnl_pct for t in result.trades]
    max_consec = 0
    consec = 0
    for p in pnls:
        if p <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    print(f"\n  Max Consec Losses:  {max_consec}")

    return m


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("SPRING REVERSAL — MULTI-TIMEFRAME CONFIRMATION RESEARCH")
    print("=" * 70)

    store = OHLCVStore()
    df_1h = store.load("okx", "BTC/USDT", "1h")
    print(f"\nOKX BTC/USDT 1h: {len(df_1h)} bars, {df_1h.index[0]} to {df_1h.index[-1]}")

    # Create 4h bars
    df_4h = resample_to_4h(df_1h)
    print(f"Resampled 4h: {len(df_4h)} bars, {df_4h.index[0]} to {df_4h.index[-1]}")

    engine_kwargs = dict(
        initial_capital=10000, commission=0.0005, slippage=0.0005
    )

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
        "bb_low": 0.2,
        "bb_high": 0.6,
    }

    # ========================================================================
    # VARIANT 0: Baseline (no MTF)
    # ========================================================================
    print("\n" + "=" * 70)
    print("VARIANT 0: BASELINE (1h SMA200 + BB 0.2-0.6, no MTF)")
    print("=" * 70)

    base_params_0 = {**base_params, "df_4h": df_4h}
    strategy_0 = SpringMTFStrategy(params=base_params_0)
    engine_0 = BacktestEngine(**engine_kwargs)
    result_0 = engine_0.run(
        df_1h, strategy_0,
        symbol="BTC/USDT",
        stop_loss_pct=base_params["stop_pct"],
        take_profit_pct=base_params["target_pct"],
        max_hold_bars=base_params["hold_hours"],
    )
    m0 = print_metrics(result_0, "BASELINE (no MTF filter)")

    # Walk-forward
    wf0 = walk_forward(df_1h, SpringMTFStrategy, base_params_0, **engine_kwargs)
    wf0_pos = sum(1 for s in wf0 if s["return"] > 0)
    wf0_sharpes = [s["sharpe"] for s in wf0]
    print(f"\n  Walk-Forward ({len(wf0)} splits):")
    for i, s in enumerate(wf0):
        status = "✅" if s["return"] > 0 else "❌"
        print(f"    Split {i+1}: {s['start'].strftime('%Y-%m')}→{s['end'].strftime('%Y-%m')}  trades={s['trades']:3d}  return={s['return']:+.1f}%  sharpe={s['sharpe']:+.2f}  {status}")
    print(f"    OOS Profitable: {wf0_pos}/{len(wf0)} | Mean OOS Sharpe: {np.mean(wf0_sharpes):+.2f}")

    # ========================================================================
    # VARIANTS: Test each MTF filter
    # ========================================================================

    variants = [
        ("V1: 4h Close > 4h SMA200", {"mtf_4h_above_sma200": True}),
        ("V2: 4h SMA50 > 4h SMA200 (Golden Cross)", {"mtf_4h_golden_cross": True}),
        ("V3: 4h Close > 4h SMA50", {"mtf_4h_above_sma50": True}),
        ("V4: 4h ADX > 20 (Trending)", {"mtf_4h_adx_trending": True}),
        ("V5: 4h GC + 4h > SMA50 (Combo)", {
            "mtf_4h_golden_cross": True,
            "mtf_4h_above_sma50": True,
        }),
        ("V6: 4h GC + 4h ADX > 20 (Combo)", {
            "mtf_4h_golden_cross": True,
            "mtf_4h_adx_trending": True,
        }),
    ]

    all_results = [("BASELINE", m0, wf0, wf0_pos, wf0_sharpes)]

    for label, mtf_filters in variants:
        print(f"\n{'='*70}")
        print(f"{label}")
        print(f"{'='*70}")

        p = {**base_params, **mtf_filters, "df_4h": df_4h}
        strategy = SpringMTFStrategy(params=p)
        engine = BacktestEngine(**engine_kwargs)
        result = engine.run(
            df_1h, strategy,
            symbol="BTC/USDT",
            stop_loss_pct=p["stop_pct"],
            take_profit_pct=p["target_pct"],
            max_hold_bars=p["hold_hours"],
        )
        m = print_metrics(result, label)

        # Walk-forward
        wf = walk_forward(df_1h, SpringMTFStrategy, p, **engine_kwargs)
        wf_pos = sum(1 for s in wf if s["return"] > 0)
        wf_sharpes = [s["sharpe"] for s in wf]
        print(f"\n  Walk-Forward ({len(wf)} splits):")
        for i, s in enumerate(wf):
            status = "✅" if s["return"] > 0 else "❌"
            print(f"    Split {i+1}: {s['start'].strftime('%Y-%m')}→{s['end'].strftime('%Y-%m')}  trades={s['trades']:3d}  return={s['return']:+.1f}%  sharpe={s['sharpe']:+.2f}  {status}")
        print(f"    OOS Profitable: {wf_pos}/{len(wf)} | Mean OOS Sharpe: {np.mean(wf_sharpes):+.2f}")

        all_results.append((label, m, wf, wf_pos, wf_sharpes))

    # ========================================================================
    # COMPARISON TABLE
    # ========================================================================
    print(f"\n{'='*70}")
    print("COMPARISON: ALL VARIANTS")
    print(f"{'='*70}")

    print(f"\n  {'Variant':35s} {'Trades':>6s} {'Return':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>5s} {'WF':>5s} {'WFSharpe':>8s}")
    print(f"  {'-'*87}")
    for label, m, wf, wf_pos, wf_sharpes in all_results:
        wf_str = f"{wf_pos}/{len(wf)}"
        print(f"  {label:35s} {m.total_trades:6d} {m.total_return_pct:>+7.1f}% {m.sharpe_ratio:>+6.2f} {m.max_drawdown_pct:>+6.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f} {wf_str:>5s} {np.mean(wf_sharpes):>+7.2f}")

    # ========================================================================
    # SIGNAL OVERLAP ANALYSIS
    # ========================================================================
    print(f"\n{'='*70}")
    print("SIGNAL OVERLAP ANALYSIS")
    print(f"{'='*70}")

    # Get signals for each variant
    sigs = {}
    all_variant_params = [
        ("BASELINE", base_params_0),
    ] + [(label, {**base_params, **mtf_filters, "df_4h": df_4h}) for label, mtf_filters in variants]

    for label, p in all_variant_params:
        strategy = SpringMTFStrategy(params=p)
        sig = strategy.generate_signal(df_1h)
        sigs[label] = sig

    # Overlap matrix
    labels = [l for l, _ in all_variant_params]
    n = len(labels)
    print(f"\n  Signal Overlap Matrix (% of baseline signals):")
    print(f"  {'':30s}", end="")
    for l in labels:
        print(f" {l.split(':')[0][:8]:>8s}", end="")
    print()

    baseline_sig = sigs["BASELINE"]
    baseline_count = baseline_sig.sum()
    print(f"  Baseline signal count: {baseline_count}")

    for l1 in labels:
        print(f"  {l1:30s}", end="")
        for l2 in labels:
            overlap = (sigs[l1] & sigs[l2]).sum()
            pct = overlap / max(baseline_count, 1) * 100
            print(f" {pct:>7.1f}%", end="")
        print()

    # ========================================================================
    # BINANCE CROSS-VALIDATION (best variant)
    # ========================================================================
    print(f"\n{'='*70}")
    print("BINANCE CROSS-VALIDATION")
    print(f"{'='*70}")

    df_binance = store.load("binance", "BTC/USDT", "1h")
    df_binance_4h = resample_to_4h(df_binance)
    print(f"Binance BTC/USDT 1h: {len(df_binance)} bars")

    # Test baseline on Binance
    bp0 = {**base_params, "df_4h": df_binance_4h}
    bs0 = SpringMTFStrategy(params=bp0)
    be0 = BacktestEngine(**engine_kwargs)
    br0 = be0.run(df_binance, bs0, symbol="BTC/USDT",
        stop_loss_pct=bp0["stop_pct"],
        take_profit_pct=bp0["target_pct"],
        max_hold_bars=bp0["hold_hours"])
    bm0 = print_metrics(br0, "BINANCE BASELINE")

    # Test best MTF variant on Binance (V2: 4h Golden Cross)
    bp2 = {**base_params, "mtf_4h_golden_cross": True, "df_4h": df_binance_4h}
    bs2 = SpringMTFStrategy(params=bp2)
    be2 = BacktestEngine(**engine_kwargs)
    br2 = be2.run(df_binance, bs2, symbol="BTC/USDT",
        stop_loss_pct=bp2["stop_pct"],
        take_profit_pct=bp2["target_pct"],
        max_hold_bars=bp2["hold_hours"])
    bm2 = print_metrics(br2, "BINANCE V2 (4h Golden Cross)")

    # Comparison
    print(f"\n  Cross-Exchange Comparison:")
    print(f"  {'Metric':20s} {'OKX Baseline':>12s} {'OKX V2':>12s} {'BNC Baseline':>12s} {'BNC V2':>12s}")
    print(f"  {'-'*62}")
    for metric_name, m_okx0, m_okx2, m_bnc0, m_bnc2 in [
        ("Sharpe", m0.sharpe_ratio, all_results[2][1].sharpe_ratio, bm0.sharpe_ratio, bm2.sharpe_ratio),
        ("Return", m0.total_return_pct, all_results[2][1].total_return_pct, bm0.total_return_pct, bm2.total_return_pct),
        ("Max DD", m0.max_drawdown_pct, all_results[2][1].max_drawdown_pct, bm0.max_drawdown_pct, bm2.max_drawdown_pct),
        ("Win Rate", m0.win_rate_pct, all_results[2][1].win_rate_pct, bm0.win_rate_pct, bm2.win_rate_pct),
        ("PF", m0.profit_factor, all_results[2][1].profit_factor, bm0.profit_factor, bm2.profit_factor),
        ("Trades", float(m0.total_trades), float(all_results[2][1].total_trades), float(bm0.total_trades), float(bm2.total_trades)),
    ]:
        if metric_name == "Trades":
            print(f"  {metric_name:20s} {m_okx0:>12.0f} {m_okx2:>12.0f} {m_bnc0:>12.0f} {m_bnc2:>12.0f}")
        elif metric_name == "Win Rate":
            print(f"  {metric_name:20s} {m_okx0:>11.1f}% {m_okx2:>11.1f}% {m_bnc0:>11.1f}% {m_bnc2:>11.1f}%")
        else:
            print(f"  {metric_name:20s} {m_okx0:>+11.2f} {m_okx2:>+11.2f} {m_bnc0:>+11.2f} {m_bnc2:>+11.2f}")

    print("\n" + "=" * 70)
    print("RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
