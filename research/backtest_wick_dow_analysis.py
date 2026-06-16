"""
Wick Inversion — Day-of-Week Extended Analysis
===============================================
Follow-up: Test "Skip Thu" and "Skip Thu+Sat" with walk-forward validation.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, wick_imbalance, pct_change_rolling
)
from cryptoquant.strategy.base import Strategy


def classify_day_of_week(ts):
    if ts > 1e15: ts = ts // 1_000_000
    if ts > 1e12: ts = ts // 1000
    return pd.Timestamp(ts, unit='s').dayofweek

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ============================================================================
# Base Wick Vol Gate strategy
# ============================================================================

class WickVolGateOpt(Strategy):
    timeframe = "1h"
    min_bars = 300
    version = "vol_gate_opt"
    DEFAULT_PARAMS = {
        "imbalance_window": 6, "imbalance_threshold": 0.25,
        "price_lookback": 6, "price_floor": -0.5,
        "stop_pct": 3.0, "target_pct": 2.5, "hold_hours": 16,
    }

    @property
    def name(self) -> str:
        return "Wick_VolGate_Opt"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])
        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        signal = signal & (vol_ratio > 1.0)
        return signal.astype(int)


class WickSkipDays(Strategy):
    """Wick vol gate + skip specified days of week."""
    timeframe = "1h"
    min_bars = 300
    version = "skip_days"
    DEFAULT_PARAMS = {
        "imbalance_window": 6, "imbalance_threshold": 0.25,
        "price_lookback": 6, "price_floor": -0.5,
        "stop_pct": 3.0, "target_pct": 2.5, "hold_hours": 16,
        "skip_days": [],  # 0=Mon, 3=Thu, 5=Sat
    }

    @property
    def name(self) -> str:
        return "Wick_SkipDays"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])
        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        signal = signal & (vol_ratio > 1.0)

        skip = self.params.get("skip_days", [])
        if skip:
            dows = pd.Series(df.index).apply(
                lambda ts: classify_day_of_week(getattr(ts, 'value', ts))
            )
            signal = signal & (~dows.isin(skip)).values

        return signal.astype(int)


def walk_forward(df, skip_days, n_splits=6, label=""):
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()
        if len(split_df) < 300:
            continue
        strategy = WickSkipDays()
        strategy.params["skip_days"] = skip_days
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            split_df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )
        trades = result.trades
        lin_sum = sum(t.pnl_pct for t in trades)
        sharpe = result.metrics.sharpe_ratio
        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        results.append({
            "split": s+1, "period": f"{start_date}->{end_date}",
            "trades": len(trades), "sum": lin_sum, "sharpe": sharpe,
        })
    return results


def print_wf_table(results, label):
    print(f"\n--- {label} ---")
    print(f"{'Split':>5s}  {'Period':20s}  {'Trades':>6s}  {'Sum':>8s}  {'Sharpe':>7s}  {'Status':>6s}")
    print("-" * 65)
    for r in results:
        status = "OK" if r["sum"] > 0 else "FAIL"
        print(f"  {r['split']:>3d}  {r['period']:20s}  {r['trades']:>6d}  {r['sum']:>+7.1f}%  {r['sharpe']:>+7.2f}  {status:>6s}")
    profitable = sum(1 for r in results if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"\n  -> {profitable}/{len(results)} OOS profitable")
    print(f"  -> Mean OOS Sharpe: {mean_sharpe:+.2f}")
    print(f"  -> Total OOS Sum: {total_sum:+.1f}%")
    return profitable, mean_sharpe


def print_result(result, label):
    m = result.metrics
    trades = result.trades
    exit_counts = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
    exit_pnls = {}
    for t in trades:
        if t.exit_reason not in exit_pnls:
            exit_pnls[t.exit_reason] = []
        exit_pnls[t.exit_reason].append(t.pnl_pct)
    max_consec = 0
    current = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Total Trades:       {len(trades)}")
    print(f"  Total Return:       {m.total_return_pct:+.1f}%")
    print(f"  Linear Sum:         {sum(t.pnl_pct for t in trades):+.1f}%")
    print(f"  Annualized Return:  {m.annualized_return_pct:+.1f}%")
    print(f"  Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"  Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"  Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"  Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"  Avg Win:            {m.avg_win_pct:+.3f}%")
    print(f"  Avg Loss:           {m.avg_loss_pct:+.3f}%")
    print(f"  Profit Factor:      {m.profit_factor:.2f}")
    print(f"  Max Consec Losses:  {max_consec}")
    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        count = exit_counts.get(reason, 0)
        pnl_list = exit_pnls.get(reason, [0])
        avg_pnl = np.mean(pnl_list) if pnl_list else 0
        total_pnl = sum(pnl_list)
        pct = count / len(trades) * 100 if trades else 0
        print(f"    {reason:15s} {count:>4d} ({pct:>4.1f}%)  avg={avg_pnl:>+7.3f}%  total={total_pnl:>+8.1f}%")

    return {
        "label": label, "trades": len(trades),
        "compound": m.total_return_pct, "sharpe": m.sharpe_ratio,
        "max_dd": m.max_drawdown_pct, "win_rate": m.win_rate_pct,
        "profit_factor": m.profit_factor,
    }


def main():
    print("=" * 70)
    print("  WICK — DAY-OF-WEEK EXTENDED ANALYSIS")
    print("  Vol Gate v4.5.0: s3.0/t2.5/h16")
    print("=" * 70)

    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nData: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")

    configs = [
        ("Baseline (no skip)", []),
        ("Skip Thu (dow=3)", [3]),
        ("Skip Sat (dow=5)", [5]),
        ("Skip Thu+Sat (dow=3,5)", [3, 5]),
        ("Skip Thu+Fri+Sat (dow=3,4,5)", [3, 4, 5]),
    ]

    all_results = []

    for label, skip_days in configs:
        strategy = WickSkipDays()
        strategy.params["skip_days"] = skip_days
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )
        stats = print_result(result, label)
        all_results.append(stats)

        # Walk-forward
        wf_results = walk_forward(df, skip_days, n_splits=6, label=f"WF: {label}")
        print_wf_table(wf_results, f"WF: {label}")

    # Summary
    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"{'Config':35s} {'Trades':>6s} {'Compound':>9s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 85)
    for r in all_results:
        print(f"{r['label']:35s} {r['trades']:>6d} {r['compound']:>+8.1f}% {r['sharpe']:>+7.2f} {r['max_dd']:>6.1f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")

    # Saturday trades analysis
    print(f"\n{'='*70}")
    print(f"  PER-DAY DEEP DIVE")
    print(f"{'='*70}")

    strategy = WickVolGateOpt()
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    result = engine.run(
        df, strategy, symbol="BTC/USDT",
        stop_loss_pct=strategy.params["stop_pct"],
        take_profit_pct=strategy.params["target_pct"],
        max_hold_bars=strategy.params["hold_hours"],
    )

    # Tag trades by day of week and year
    from collections import defaultdict
    dow_year_trades = defaultdict(lambda: defaultdict(list))
    for t in result.trades:
        dow = classify_day_of_week(t.entry_time)
        year = pd.Timestamp(t.entry_time, unit='ms' if t.entry_time > 1e12 else 's').year
        dow_year_trades[dow][year].append(t.pnl_pct)

    for dow in range(7):
        years = sorted(dow_year_trades[dow].keys())
        year_stats = []
        for y in years:
            pnls = dow_year_trades[dow][y]
            year_stats.append(f"{y}: {len(pnls)}t/{sum(pnls):+.1f}%")
        print(f"  {DAY_NAMES[dow]:>5s} per year: {' | '.join(year_stats)}")

    # Thursday hour breakdown
    print(f"\n  Thursday hour breakdown:")
    thu_trades = [t for t in result.trades if classify_day_of_week(t.entry_time) == 3]
    from collections import Counter
    hour_pnls = defaultdict(list)
    for t in thu_trades:
        ts = t.entry_time
        if ts > 1e15: ts = ts // 1_000_000
        if ts > 1e12: ts = ts // 1000
        hour = (ts // 3600) % 24
        hour_pnls[hour].append(t.pnl_pct)

    for hour in sorted(hour_pnls.keys()):
        pnls = hour_pnls[hour]
        print(f"    {hour:>2d}h UTC: {len(pnls):>3d} trades, sum={sum(pnls):>+7.1f}%, avg={np.mean(pnls):>+6.3f}%, wr={sum(1 for p in pnls if p>0)/len(pnls)*100:.0f}%")

    print(f"\n{'='*70}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
