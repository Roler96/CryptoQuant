"""Spring Reversal — Vol Gate Entry Filter Research.

Tests whether adding an ATR ratio volatility gate as an ENTRY filter
(not exit adjustment) improves Spring Reversal performance.

The vol gate was a breakthrough for Wick (v4.5.0: 6/6 WF, mean OOS +1.26).
Spring's regime analysis showed "Very High Vol" is the best vol regime
(+0.76 Sharpe), but the vol relationship is non-monotonic. This script
tests whether a vol gate can complement or replace the BB %B filter.

Hypothesis: Vol gate (> 1.0 or > 1.5) filters out weak Spring signals
in low-vol chop while preserving signals in meaningful high-vol environments
where the "failed breakdown" trap is more significant.

Experiment:
  1. Filter comparison: SMA200 / SMA200+BB / SMA200+VolGate variants
  2. Exit parameter grid sweep for best filter
  3. Walk-forward validation (7 splits) for top configurations
  4. Comparison with existing research baselines
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    spring_reversal_signal, sma, atr, bollinger_bands,
)


class SpringVolGate(Strategy):
    """Spring Reversal with configurable entry filters.

    Additive filters that can be independently toggled:
      - sma200_filter: only take signals when close > SMA(200)
      - bb_filter: only take signals when BB %B in [bb_low, bb_high)
      - vol_gate: only take signals when vol_ratio > vol_thresh
    """

    timeframe = "1h"
    min_bars = 300
    version = "research"

    DEFAULT_PARAMS = {
        "lookback": 20,
        "vol_mult": 1.5,
        "close_pct": 0.5,
        # Exit params (overridden at engine level)
        "stop_pct": 3.0,
        "target_pct": 3.0,
        "hold_hours": 16,
        # Filters
        "sma200_filter": True,
        "bb_filter": False,
        "bb_period": 20,
        "bb_std": 2.0,
        "bb_low": 0.2,
        "bb_high": 0.6,
        "vol_gate": False,
        "vol_period": 14,
        "vol_thresh": 1.0,  # ATR ratio > 1.0 = above median
    }

    @property
    def name(self) -> str:
        parts = ["Spring"]
        if self.params.get("sma200_filter"):
            parts.append("SMA200")
        if self.params.get("bb_filter"):
            parts.append(f"BB{self.params['bb_low']:.2f}-{self.params['bb_high']:.2f}")
        if self.params.get("vol_gate"):
            parts.append(f"VolG{self.params['vol_thresh']:.1f}")
        return "+".join(parts)

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        signal = spring_reversal_signal(
            df,
            lookback=self.params["lookback"],
            vol_mult=self.params["vol_mult"],
            close_pct=self.params["close_pct"],
        )

        # SMA200 trend filter
        if self.params.get("sma200_filter", False):
            close_series: pd.Series = df["close"]  # type: ignore[assignment]
            sma200 = sma(close_series, 200)
            signal = signal & (close_series > sma200)

        # BB %B zone filter
        if self.params.get("bb_filter", False):
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

        # Vol gate entry filter
        if self.params.get("vol_gate", False):
            atr14 = atr(df, self.params["vol_period"])
            median_atr = atr14.rolling(200).median()
            vol_ratio = atr14 / median_atr
            signal = signal & (vol_ratio > self.params["vol_thresh"])

        return signal.astype(int)


def run_backtest(df, params, stop, target, hold, commission=0.0005, slippage=0.0005):
    """Run a single backtest with given filter + exit parameters."""
    strategy = SpringVolGate(params=params)
    engine = BacktestEngine(
        initial_capital=10_000,
        commission=commission,
        slippage=slippage,
        use_lows_for_stops=True,
    )
    result = engine.run(
        df,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=stop,
        take_profit_pct=target,
        max_hold_bars=hold,
    )
    return result


def format_result(result, label=""):
    """Format backtest result as a metrics dict."""
    m = result.metrics
    exits = {}
    for t in result.trades:
        e = t.exit_reason or "unknown"
        exits[e] = exits.get(e, {"count": 0, "pnl_sum": 0.0})
        exits[e]["count"] += 1
        exits[e]["pnl_sum"] += t.pnl_pct

    # Compute max consecutive losses manually
    max_cons_loss = 0
    current_streak = 0
    for t in result.trades:
        if t.pnl_pct <= 0:
            current_streak += 1
            max_cons_loss = max(max_cons_loss, current_streak)
        else:
            current_streak = 0

    out = {
        "label": label,
        "trades": m.total_trades,
        "compound": (result.final_equity / result.initial_capital - 1) * 100,
        "linear_sum": sum(t.pnl_pct for t in result.trades),
        "sharpe": m.sharpe_ratio,
        "sortino": m.sortino_ratio,
        "max_dd": m.max_drawdown_pct,
        "win_rate": m.win_rate_pct,
        "avg_win": m.avg_win_pct,
        "avg_loss": m.avg_loss_pct,
        "pf": m.profit_factor,
        "max_cons_loss": max_cons_loss,
        "exits": exits,
    }
    return out


def walk_forward(df, params, stop, target, hold, n_splits=7):
    """Walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    for s in range(n_splits):
        end_idx = n - (n_splits - s) * slot
        start_idx = max(0, end_idx - slot)
        split_df = df.iloc[start_idx:end_idx]
        if len(split_df) < 300:
            results.append({"split": s+1, "error": "too few bars"})
            continue
        r = run_backtest(split_df, params, stop, target, hold)
        results.append({
            "split": s + 1,
            "start": str(split_df.index[0].date()),
            "end": str(split_df.index[-1].date()),
            "trades": r.metrics.total_trades,
            "return": sum(t.pnl_pct for t in r.trades),
            "sharpe": r.metrics.sharpe_ratio,
            "dd": r.metrics.max_drawdown_pct,
            "win_rate": r.metrics.win_rate_pct,
        })
    return results


def print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_result(r):
    print(f"\n  {r['label']}")
    print(f"  {'─'*50}")
    print(f"  Trades:           {r['trades']:>5d}")
    print(f"  Compound Return:  {r['compound']:>+8.1f}%")
    print(f"  Linear Sum:       {r['linear_sum']:>+8.1f}%")
    print(f"  Sharpe Ratio:     {r['sharpe']:>+8.2f}")
    print(f"  Sortino Ratio:    {r['sortino']:>+8.2f}")
    print(f"  Max Drawdown:     {r['max_dd']:>+8.1f}%")
    print(f"  Win Rate:         {r['win_rate']:>7.1f}%")
    print(f"  Avg Win:          {r['avg_win']:>+8.2f}%")
    print(f"  Avg Loss:         {r['avg_loss']:>+8.2f}%")
    print(f"  Profit Factor:    {r['pf']:>8.2f}")
    print(f"  Max Cons Losses:  {r['max_cons_loss']:>5d}")
    print(f"\n  Exit Breakdown:")
    for reason, data in sorted(r.get("exits", {}).items()):
        n_exits = data["count"]
        pct = n_exits / r["trades"] * 100 if r["trades"] else 0
        avg_pnl = data["pnl_sum"] / n_exits if n_exits else 0
        print(f"    {reason:<16s} {n_exits:>4d} ({pct:>5.1f}%)  avg={avg_pnl:>+7.2f}%  total={data['pnl_sum']:>+8.1f}%")


def print_wf(wf_results, label=""):
    print(f"\n  Walk-Forward ({label}):")
    profitable = 0
    sharpes = []
    for r in wf_results:
        if "error" in r:
            print(f"    Split {r['split']}: {r['error']}")
            continue
        status = "✅" if r["return"] > 0 else "❌"
        if r["return"] > 0:
            profitable += 1
        sharpes.append(r["sharpe"])
        print(f"    Split {r['split']}: {r['start']}→{r['end']}  "
              f"trades={r['trades']:>3d}  return={r['return']:>+7.1f}%  "
              f"sharpe={r['sharpe']:>+7.2f}  dd={r['dd']:>+6.1f}%  {status}")
    if sharpes:
        mean_sharpe = sum(sharpes) / len(sharpes)
        print(f"    → {profitable}/{len(wf_results)} OOS profitable | Mean OOS Sharpe: {mean_sharpe:+.2f}")


# ────────────────────────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  Spring Reversal — Vol Gate Entry Filter Research")
    print("  OKX BTC/USDT 1h, 2019-2026, commission=5bps, slippage=5bps")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\n  Data loaded: {len(df):,} bars, {df.index[0]} → {df.index[-1]}")

    # ── EXPERIMENT 1: Filter Comparison (fixed exits s3.0/t3.0/h16) ──
    print_header("EXPERIMENT 1: Filter Comparison (s3.0/t3.0/h16)")

    filters_to_test = [
        {
            "label": "No Filters (Baseline)",
            "params": {"sma200_filter": False, "bb_filter": False, "vol_gate": False},
        },
        {
            "label": "SMA200 Only",
            "params": {"sma200_filter": True, "bb_filter": False, "vol_gate": False},
        },
        {
            "label": "SMA200 + BB [0.20, 0.60)",
            "params": {"sma200_filter": True, "bb_filter": True, "bb_low": 0.20, "bb_high": 0.60, "vol_gate": False},
        },
        {
            "label": "SMA200 + VolGate > 1.0 (above median)",
            "params": {"sma200_filter": True, "bb_filter": False, "vol_gate": True, "vol_thresh": 1.0},
        },
        {
            "label": "SMA200 + VolGate > 1.5 (very high vol)",
            "params": {"sma200_filter": True, "bb_filter": False, "vol_gate": True, "vol_thresh": 1.5},
        },
        {
            "label": "SMA200 + VolGate > 0.7 (above low vol)",
            "params": {"sma200_filter": True, "bb_filter": False, "vol_gate": True, "vol_thresh": 0.7},
        },
        {
            "label": "SMA200 + BB [0.20,0.60) + VolGate > 1.0",
            "params": {"sma200_filter": True, "bb_filter": True, "bb_low": 0.20, "bb_high": 0.60,
                       "vol_gate": True, "vol_thresh": 1.0},
        },
        {
            "label": "SMA200 + BB [0.15,0.65) + VolGate > 1.0",
            "params": {"sma200_filter": True, "bb_filter": True, "bb_low": 0.15, "bb_high": 0.65,
                       "vol_gate": True, "vol_thresh": 1.0},
        },
        {
            "label": "VolGate > 1.5 Only (no SMA200)",
            "params": {"sma200_filter": False, "bb_filter": False, "vol_gate": True, "vol_thresh": 1.5},
        },
    ]

    exp1_results = []
    for f in filters_to_test:
        r = run_backtest(df, f["params"], stop=3.0, target=3.0, hold=16)
        fmt = format_result(r, f["label"])
        exp1_results.append(fmt)
        print_result(fmt)

    # Identify best filter (excluding baseline/no-filter)
    valid = [r for r in exp1_results if r["trades"] >= 10
             and "No Filters" not in r["label"]]
    best = max(valid, key=lambda r: r["sharpe"])
    print(f"\n  >>> Best Filter: {best['label']} (Sharpe {best['sharpe']:+.2f}, {best['trades']} trades)")

    # ── EXPERIMENT 2: Exit Parameter Grid for Top Filters ──
    print_header("EXPERIMENT 2: Exit Parameter Grid (Top 4 Filters)")

    top_filters = sorted(valid, key=lambda r: r["sharpe"], reverse=True)[:4]

    stops = [2.0, 2.5, 3.0, 3.5, 4.0]
    targets = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    holds = [8, 10, 12, 14, 16, 20, 24]

    exp2_top = []  # top results across all filters

    for f_entry in top_filters:
        # Find the original params dict
        orig = next(ft for ft in filters_to_test if ft["label"] == f_entry["label"])
        params = orig["params"]
        print(f"\n  ── Grid search for: {f_entry['label']} ──")

        best_for_filter = None
        best_sharpe = -999

        for stop in stops:
            for target in targets:
                for hold in holds:
                    # Skip obviously bad: stop <= target
                    if stop <= target:
                        continue
                    r = run_backtest(df, params, stop=stop, target=target, hold=hold)
                    s = r.metrics.sharpe_ratio
                    if s > best_sharpe:
                        best_sharpe = s
                        best_for_filter = {
                            "stop": stop, "target": target, "hold": hold,
                            "sharpe": s, "trades": r.metrics.total_trades,
                            "return": sum(t.pnl_pct for t in r.trades),
                            "dd": r.metrics.max_drawdown_pct,
                            "wr": r.metrics.win_rate_pct,
                            "pf": r.metrics.profit_factor,
                        }

        if best_for_filter:
            print(f"    Best: s{best_for_filter['stop']:.1f}/"
                  f"t{best_for_filter['target']:.1f}/"
                  f"h{best_for_filter['hold']}d  "
                  f"Sharpe={best_for_filter['sharpe']:+.2f}  "
                  f"trades={best_for_filter['trades']}  "
                  f"return={best_for_filter['return']:+.1f}%")
            best_for_filter["filter"] = f_entry["label"]
            best_for_filter["params"] = params
            exp2_top.append(best_for_filter)

    # Sort and show top 10 overall
    exp2_top.sort(key=lambda x: x["sharpe"], reverse=True)
    print(f"\n  Top 10 Overall (by Sharpe):")
    print(f"  {'Filter':<42s} {'Stop':>5s} {'Tgt':>5s} {'Hold':>5s} {'Trades':>6s} {'Return':>8s} {'Sharpe':>7s} {'DD':>7s} {'WR':>6s} {'PF':>6s}")
    print(f"  {'─'*42} {'─'*5} {'─'*5} {'─'*5} {'─'*6} {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*6}")
    for i, r in enumerate(exp2_top[:10]):
        print(f"  {r['filter']:<42s} {r['stop']:>4.1f}% {r['target']:>4.1f}% {r['hold']:>4d}h "
              f"{r['trades']:>6d} {r['return']:>+7.1f}% {r['sharpe']:>+7.2f} "
              f"{r['dd']:>+6.1f}% {r['wr']:>5.1f}% {r['pf']:>5.2f}")

    # ── EXPERIMENT 3: Full Backtest for Best Configuration ──
    print_header("EXPERIMENT 3: Full Backtest — Best Configuration")

    best_config = exp2_top[0]
    best_params = best_config["params"]
    best_stop = best_config["stop"]
    best_target = best_config["target"]
    best_hold = best_config["hold"]

    print(f"\n  Configuration: {best_config['filter']}")
    print(f"  Exits: s{best_stop:.1f}%/t{best_target:.1f}%/h{best_hold}h")

    best_result = run_backtest(df, best_params, best_stop, best_target, best_hold)
    best_fmt = format_result(best_result, "BEST CONFIG")
    print_result(best_fmt)

    # ── EXPERIMENT 4: Walk-Forward Validation ──
    print_header("EXPERIMENT 4: Walk-Forward Validation")

    # Test best config
    print(f"\n  ── Best Config: {best_config['filter']} s{best_stop:.1f}/t{best_target:.1f}/h{best_hold}h ──")
    wf_best = walk_forward(df, best_params, best_stop, best_target, best_hold)
    print_wf(wf_best, "Best Config")

    # Also test the current production Spring config for reference
    prod_params = {"sma200_filter": True, "bb_filter": True,
                   "bb_low": 0.15, "bb_high": 0.65, "vol_gate": False}
    print(f"\n  ── Production Config: SMA200+BB[0.15,0.65) s3.0/t2.5/h24 ──")
    wf_prod = walk_forward(df, prod_params, stop=3.0, target=2.5, hold=24)
    print_wf(wf_prod, "Production")

    # Also test with the vol gate baseline
    vol_params = {"sma200_filter": True, "bb_filter": False, "vol_gate": True, "vol_thresh": 1.0}
    print(f"\n  ── SMA200+VolGate>1.0 s3.0/t3.0/h16 ──")
    wf_vol = walk_forward(df, vol_params, stop=3.0, target=3.0, hold=16)
    print_wf(wf_vol, "VolGate")

    # ── EXPERIMENT 5: Comparison with Existing Research Baselines ──
    print_header("EXPERIMENT 5: Comparison Summary")

    print(f"\n  {'Configuration':<45s} {'Trades':>6s} {'Return':>8s} {'Sharpe':>7s} {'DD':>7s} {'WR':>6s} {'PF':>6s}")
    print(f"  {'─'*45} {'─'*6} {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*6}")

    # Re-run key baselines for consistent comparison
    baselines = [
        ("Baseline: No Filters (s3/t3/h16)", {"sma200_filter": False, "bb_filter": False, "vol_gate": False}, 3.0, 3.0, 16),
        ("SMA200 Only (s3/t3/h16)", {"sma200_filter": True, "bb_filter": False, "vol_gate": False}, 3.0, 3.0, 16),
        ("SMA200+BB[0.20,0.60) s3/t3/h16", {"sma200_filter": True, "bb_filter": True, "bb_low": 0.20, "bb_high": 0.60, "vol_gate": False}, 3.0, 3.0, 16),
        ("SMA200+BB[0.15,0.65) s3.0/t2.5/h24 (v1.1.0)", {"sma200_filter": True, "bb_filter": True, "bb_low": 0.15, "bb_high": 0.65, "vol_gate": False}, 3.0, 2.5, 24),
    ]
    for label, params, stop, target, hold in baselines:
        r = run_backtest(df, params, stop=stop, target=target, hold=hold)
        fmt = format_result(r, label)
        print(f"  {label:<45s} {fmt['trades']:>6d} {fmt['linear_sum']:>+7.1f}% {fmt['sharpe']:>+7.2f} {fmt['max_dd']:>+6.1f}% {fmt['win_rate']:>5.1f}% {fmt['pf']:>5.2f}")

    # Best vol gate config
    print(f"  {'─'*45} {'─'*6} {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*6}")
    print(f"  {best_config['filter']:<45s} {best_fmt['trades']:>6d} {best_fmt['linear_sum']:>+7.1f}% {best_fmt['sharpe']:>+7.2f} {best_fmt['max_dd']:>+6.1f}% {best_fmt['win_rate']:>5.1f}% {best_fmt['pf']:>5.2f}")

    print(f"\n{'='*70}")
    print("  Research complete.")
    print(f"  Best: {best_config['filter']} s{best_stop:.1f}/t{best_target:.1f}/h{best_hold}h")
    print(f"  Sharpe: {best_fmt['sharpe']:+.2f} | Return: {best_fmt['linear_sum']:+.1f}% | MaxDD: {best_fmt['max_dd']:+.1f}%")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
