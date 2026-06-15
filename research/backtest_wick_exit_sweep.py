"""
Wick Inversion — Exit Optimization for Vol-Gated Variant
=========================================================
Quick sweep of stop/target/hold for Wick + Vol Gate (ATR > 1.0 median).
Tests 5 stops × 5 targets × 5 holds = 125 combinations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    sma, atr as atr_func, wick_imbalance, pct_change_rolling
)


class WickVolGate(Strategy):
    """Wick + vol gate (ATR ratio > 1.0 median) — parameterized exits."""
    timeframe = "1h"
    min_bars = 300
    version = "vol_gate_sweep"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.25,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 1.5,
        "hold_hours": 12,
    }

    @property
    def name(self) -> str:
        return "Wick_VolGate"

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


def main():
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"Data: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

    stops = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    targets = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
    holds = [6, 8, 10, 12, 14, 16, 20, 24]

    results = []
    total = len(stops) * len(targets) * len(holds)
    count = 0

    for stop in stops:
        for target in targets:
            for hold in holds:
                count += 1
                strategy = WickVolGate({
                    "stop_pct": stop,
                    "target_pct": target,
                    "hold_hours": hold,
                })
                engine = BacktestEngine(commission=0.0005, slippage=0.0005)
                result = engine.run(
                    df, strategy, symbol="BTC/USDT",
                    stop_loss_pct=stop,
                    take_profit_pct=target,
                    max_hold_bars=hold,
                )
                m = result.metrics
                trades = result.trades
                lin_sum = sum(t.pnl_pct for t in trades)
                results.append({
                    "stop": stop, "target": target, "hold": hold,
                    "trades": len(trades),
                    "sharpe": m.sharpe_ratio,
                    "compound": m.total_return_pct,
                    "max_dd": m.max_drawdown_pct,
                    "win_rate": m.win_rate_pct,
                    "profit_factor": m.profit_factor,
                    "linear_sum": lin_sum,
                })
                if count % 20 == 0:
                    print(f"  Progress: {count}/{total}")

    # Sort by Sharpe
    results.sort(key=lambda x: x["sharpe"], reverse=True)

    print(f"\n{'='*90}")
    print(f"  EXIT OPTIMIZATION — Wick + Vol Gate (ATR > 1.0) — Top 20 by Sharpe")
    print(f"{'='*90}")
    print(f"{'Stp':>4s} {'Tgt':>5s} {'Hld':>4s} {'Trd':>5s} {'Sharpe':>7s} {'Cmpd':>8s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 65)
    for r in results[:20]:
        print(f"{r['stop']:>4.1f}% {r['target']:>4.2f}% {r['hold']:>4d}h {r['trades']:>5d} {r['sharpe']:>+7.2f} {r['compound']:>+7.1f}% {r['max_dd']:>6.1f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")

    # Baseline comparison
    print(f"\n{'='*90}")
    print(f"  BASELINE (s3.0, t1.5, h12) vs TOP CONFIG")
    print(f"{'='*90}")
    for r in results[:1]:
        print(f"  Top:    s{r['stop']:.1f}%, t{r['target']:.2f}%, h{r['hold']}h → Sharpe {r['sharpe']:+.2f}, Cmpd {r['compound']:+.1f}%, DD {r['max_dd']:.1f}%, {r['trades']} trades")
    # Find baseline
    baseline = [r for r in results if r["stop"] == 3.0 and r["target"] == 1.5 and r["hold"] == 12]
    if baseline:
        b = baseline[0]
        print(f"  Base:   s{b['stop']:.1f}%, t{b['target']:.2f}%, h{b['hold']}h → Sharpe {b['sharpe']:+.2f}, Cmpd {b['compound']:+.1f}%, DD {b['max_dd']:.1f}%, {b['trades']} trades")

    # Top by MaxDD
    results_by_dd = sorted(results, key=lambda x: x["max_dd"])
    print(f"\n{'='*90}")
    print(f"  TOP 10 BY LOWEST MAX DD (Sharpe > 0.3)")
    print(f"{'='*90}")
    for r in results_by_dd:
        if r["sharpe"] > 0.3:
            print(f"  s{r['stop']:.1f}%, t{r['target']:.2f}%, h{r['hold']}h → Sharpe {r['sharpe']:+.2f}, DD {r['max_dd']:.1f}%, {r['trades']} trades, WR {r['win_rate']:.1f}%")


if __name__ == "__main__":
    main()
