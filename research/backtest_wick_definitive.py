"""
Wick Inversion — Definitive Evaluation
=======================================
Clean evaluation using the BacktestEngine (not custom backtest loops).
Resolves discrepancies between different research scripts' backtest functions.
Uses lows-based stop checking, compound returns, proper commission/slippage.

Tests:
1. Wick baseline (no filters)
2. Wick + vol gate (ATR ratio > 1.0)
3. Wick + SMA200
4. Wick + vol gate + SMA200
5. Wick with imb=0.35 (higher threshold)
6. Wick with imb=0.35 + SMA200
7. Wick with imb=0.35 + SMA200 + vol gate

Each with walk-forward validation (6 splits).
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


# ============================================================================
# Wick Strategy variants
# ============================================================================

class WickBaseline(Strategy):
    """Wick baseline — no filters, imb=0.25"""
    timeframe = "1h"
    min_bars = 100
    version = "baseline"

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
        return "Wick_Baseline"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])
        return signal.astype(int)


class WickVolGate(Strategy):
    """Wick + vol gate (ATR ratio > 1.0 median)"""
    timeframe = "1h"
    min_bars = 300
    version = "vol_gate"

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


class WickSMA200(Strategy):
    """Wick + SMA200 trend filter"""
    timeframe = "1h"
    min_bars = 300
    version = "sma200"

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
        return "Wick_SMA200"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

        sma200 = sma(df["close"], 200)
        signal = signal & (df["close"] > sma200)

        return signal.astype(int)


class WickVolSMA200(Strategy):
    """Wick + vol gate + SMA200"""
    timeframe = "1h"
    min_bars = 300
    version = "vol_sma200"

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
        return "Wick_VolSMA200"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        signal = signal & (vol_ratio > 1.0)

        sma200 = sma(df["close"], 200)
        signal = signal & (df["close"] > sma200)

        return signal.astype(int)


class WickImb35SMA200(Strategy):
    """Wick + imb=0.35 + SMA200"""
    timeframe = "1h"
    min_bars = 300
    version = "imb35_sma200"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.35,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 1.5,
        "hold_hours": 12,
    }

    @property
    def name(self) -> str:
        return "Wick_Imb35_SMA200"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

        sma200 = sma(df["close"], 200)
        signal = signal & (df["close"] > sma200)

        return signal.astype(int)


class WickImb35VolSMA200(Strategy):
    """Wick + imb=0.35 + vol gate + SMA200"""
    timeframe = "1h"
    min_bars = 300
    version = "imb35_vol_sma200"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.35,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 1.5,
        "hold_hours": 12,
    }

    @property
    def name(self) -> str:
        return "Wick_Imb35_VolSMA200"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(df["close"], self.params["price_lookback"])
        signal = (imb > self.params["imbalance_threshold"]) & (price_chg > self.params["price_floor"])

        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        signal = signal & (vol_ratio > 1.0)

        sma200 = sma(df["close"], 200)
        signal = signal & (df["close"] > sma200)

        return signal.astype(int)


# ============================================================================
# Walk-Forward Validation
# ============================================================================

def walk_forward(df, strategy_cls, n_splits=6, label=""):
    """6-split walk-forward validation."""
    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()

        if len(split_df) < 300:
            continue

        strategy = strategy_cls()
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
            "split": s + 1,
            "period": f"{start_date}→{end_date}",
            "trades": len(trades),
            "sum": lin_sum,
            "sharpe": sharpe,
        })

    return results


def print_wf_table(results, label):
    """Print walk-forward results table."""
    print(f"\n--- {label} ---")
    print(f"{'Split':>5s}  {'Period':20s}  {'Trades':>6s}  {'Sum':>8s}  {'Sharpe':>7s}  {'Status':>6s}")
    print("-" * 65)
    for r in results:
        status = "✅" if r["sum"] > 0 else "❌"
        print(f"  {r['split']:>3d}  {r['period']:20s}  {r['trades']:>6d}  {r['sum']:>+7.1f}%  {r['sharpe']:>+7.2f}  {status:>6s}")

    profitable = sum(1 for r in results if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"\n  → {profitable}/{len(results)} OOS profitable")
    print(f"  → Mean OOS Sharpe: {mean_sharpe:+.2f}")
    print(f"  → Total OOS Sum: {total_sum:+.1f}%")


def max_consecutive_losses(trades):
    """Count max consecutive losing trades."""
    max_consec = 0
    current = 0
    for t in trades:
        if t.pnl_pct <= 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0
    return max_consec


def print_backtest_result(result, label):
    """Print backtest result summary."""
    m = result.metrics
    trades = result.trades

    # Exit breakdown
    exit_counts = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    # PnL by exit reason
    exit_pnls = {}
    for t in trades:
        if t.exit_reason not in exit_pnls:
            exit_pnls[t.exit_reason] = []
        exit_pnls[t.exit_reason].append(t.pnl_pct)

    max_c_losses = max_consecutive_losses(trades)

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
    print(f"  Max Consec Losses:  {max_c_losses}")

    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        count = exit_counts.get(reason, 0)
        pnl_list = exit_pnls.get(reason, [0])
        avg_pnl = np.mean(pnl_list) if pnl_list else 0
        total_pnl = sum(pnl_list)
        pct = count / len(trades) * 100 if trades else 0
        print(f"    {reason:15s} {count:>4d} ({pct:>4.1f}%)  avg={avg_pnl:>+7.3f}%  total={total_pnl:>+8.1f}%")

    return {
        "label": label,
        "trades": len(trades),
        "compound": m.total_return_pct,
        "linear_sum": sum(t.pnl_pct for t in trades),
        "annualized": m.annualized_return_pct,
        "sharpe": m.sharpe_ratio,
        "sortino": m.sortino_ratio,
        "max_dd": m.max_drawdown_pct,
        "win_rate": m.win_rate_pct,
        "avg_win": m.avg_win_pct,
        "avg_loss": m.avg_loss_pct,
        "profit_factor": m.profit_factor,
        "max_consec": max_c_losses,
    }


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 70)
    print("  WICK INVERSION — DEFINITIVE EVALUATION")
    print("  Using BacktestEngine (lows-based stops, compound returns)")
    print("  OKX BTC/USDT 1h, 2019-2026, commission=5bps, slippage=5bps")
    print("=" * 70)

    # Load data
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nData: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

    # Test configurations
    configs = [
        (WickBaseline, "Wick Baseline (imb=0.25, no filters)"),
        (WickVolGate, "Wick + Vol Gate (ATR > 1.0 median)"),
        (WickSMA200, "Wick + SMA200"),
        (WickVolSMA200, "Wick + Vol Gate + SMA200"),
        (WickImb35SMA200, "Wick + imb=0.35 + SMA200"),
        (WickImb35VolSMA200, "Wick + imb=0.35 + Vol Gate + SMA200"),
    ]

    all_results = []

    for strategy_cls, label in configs:
        strategy = strategy_cls()
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params["stop_pct"],
            take_profit_pct=strategy.params["target_pct"],
            max_hold_bars=strategy.params["hold_hours"],
        )
        r = print_backtest_result(result, label)
        all_results.append(r)

        # Walk-forward
        wf_results = walk_forward(df, strategy_cls, n_splits=6, label=label)
        print_wf_table(wf_results, f"WF: {label}")

    # Summary comparison
    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"{'Config':35s} {'Trades':>6s} {'Compound':>8s} {'Sharpe':>7s} {'MaxDD':>7s} {'WR':>6s} {'PF':>6s}")
    print("-" * 85)
    for r in all_results:
        print(f"{r['label']:35s} {r['trades']:>6d} {r['compound']:>+7.1f}% {r['sharpe']:>+7.2f} {r['max_dd']:>6.1f}% {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f}")

    print(f"\n{'='*70}")
    print(f"  RESEARCH COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
