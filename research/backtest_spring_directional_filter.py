"""
Spring Reversal — Directional Filter Research
===============================================

Finding: Spring with proper lows-based stops has Sharpe -0.65 (not 2.72).
The documented results used closes-based stops (incorrect).

However, regime analysis shows:
- PDI > MDI (bullish direction): +8.9%, 61.1% win rate (36 trades)
- ADX > 25 (strong trend) + SMA200: +3.2%, 56.9% win rate (65 trades)

Hypothesis: Spring works when directional momentum is bullish.
Test: PDI > MDI filter, ADX filter, combined filters with walk-forward.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import new_low_bullish, sma, adx


class SpringPDIgtMDI(Strategy):
    """Spring + PDI > MDI filter (bullish directional movement)."""
    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_PDI_gt_MDI"

    def generate_signal(self, df):
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        adx_data = adx(df, 14)
        # Only take signal when PDI > MDI (bullish direction)
        bullish_dir = adx_data["pdi"] > adx_data["mdi"]
        return (spring_sig * bullish_dir.astype(int)).clip(lower=0)


class SpringADX25(Strategy):
    """Spring + ADX > 25 filter (strong trend)."""
    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_ADX25"

    def generate_signal(self, df):
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        adx_data = adx(df, 14)
        strong_trend = adx_data["adx"] > 25
        return (spring_sig * strong_trend.astype(int)).clip(lower=0)


class SpringSMA200_ADX25(Strategy):
    """Spring + SMA200 + ADX > 25 combined filter."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_SMA200_ADX25"

    def generate_signal(self, df):
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        sma_val = sma(df["close"], self.params["sma_period"])
        adx_data = adx(df, 14)
        above_sma = df["close"] > sma_val
        strong_trend = adx_data["adx"] > 25
        combined = (above_sma & strong_trend).astype(int)
        return (spring_sig * combined).clip(lower=0)


class SpringPDIgtMDI_ADX25(Strategy):
    """Spring + PDI > MDI + ADX > 25 (bullish direction + strong trend)."""
    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"
    DEFAULT_PARAMS = {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}

    @property
    def name(self):
        return "Spring_PDI_gt_MDI_ADX25"

    def generate_signal(self, df):
        df = self.preprocess(df)
        spring_sig = new_low_bullish(df, lookback=self.params["lookback"])
        adx_data = adx(df, 14)
        bullish_dir = adx_data["pdi"] > adx_data["mdi"]
        strong_trend = adx_data["adx"] > 25
        combined = (bullish_dir & strong_trend).astype(int)
        return (spring_sig * combined).clip(lower=0)


def walk_forward(df, strategy_cls, strategy_params, n_splits=6, label=""):
    """Run walk-forward validation."""
    print(f"\n{'='*70}")
    print(f"  WALK-FORWARD: {label} ({n_splits} splits)")
    print(f"{'='*70}")

    n = len(df)
    slot = n // (n_splits + 2)
    results = []

    for s in range(n_splits):
        start_idx = n - (n_splits - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()

        if len(split_df) < strategy_cls.min_bars + 50:
            continue

        strategy = strategy_cls(strategy_params)
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        result = engine.run(
            split_df, strategy, symbol="BTC/USDT",
            stop_loss_pct=strategy.params.get("stop_pct", 3.0),
            take_profit_pct=strategy.params.get("target_pct", 1.5),
            max_hold_bars=strategy.params.get("hold_hours", 6),
        )

        trades = result.trades
        n_trades = len(trades)
        lin_sum = sum(t.pnl_pct for t in trades)
        sharpe = result.metrics.sharpe_ratio

        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "  "

        print(f"  {star} {start_date}→{end_date}  trades={n_trades:>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}")
        results.append({"split": s+1, "sum": lin_sum, "sharpe": sharpe, "trades": n_trades})

    profitable = sum(1 for r in results if r["sum"] > 0)
    total = len(results)
    print(f"\n  → {profitable}/{total} OOS profitable")
    return results


def main():
    print("=" * 70)
    print("  SPRING REVERSAL — DIRECTIONAL FILTER RESEARCH")
    print("  Finding: Baseline Sharpe -0.65 (lows-based stops)")
    print("  Hypothesis: PDI > MDI filter captures bullish regime")
    print("=" * 70)

    store = OHLCVStore(db_path="data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nData: {len(df)} bars, {df.index[0]} → {df.index[-1]}")

    engine = BacktestEngine(commission=0.0005, slippage=0.0005)

    # Test directional filters
    variants = [
        (SpringPDIgtMDI, {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "PDI > MDI"),
        (SpringADX25, {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "ADX > 25"),
        (SpringSMA200_ADX25, {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "SMA200 + ADX > 25"),
        (SpringPDIgtMDI_ADX25, {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6}, "PDI > MDI + ADX > 25"),
    ]

    print("\n" + "=" * 70)
    print("  FULL-PERIOD BACKTESTS")
    print("=" * 70)

    for cls, params, label in variants:
        strategy = cls(params)
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=params["stop_pct"],
            take_profit_pct=params["target_pct"],
            max_hold_bars=params["hold_hours"],
        )
        m = result.metrics
        trades = result.trades
        exits = Counter(t.exit_reason for t in trades)
        lin_sum = sum(t.pnl_pct for t in trades)

        print(f"\n  [{label}]")
        print(f"    Trades: {m.total_trades}, Sum: {lin_sum:+.1f}%")
        print(f"    Sharpe: {m.sharpe_ratio:.2f}, Max DD: {m.max_drawdown_pct:.1f}%")
        print(f"    Win rate: {m.win_rate_pct:.1f}%, PF: {m.profit_factor:.2f}")
        print(f"    Exits: {dict(exits)}")

    # Walk-forward for promising variants
    print("\n" + "=" * 70)
    print("  WALK-FORWARD VALIDATION")
    print("=" * 70)

    # PDI > MDI
    wf_pdi = walk_forward(
        df, SpringPDIgtMDI,
        {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="PDI > MDI"
    )

    # ADX > 25
    wf_adx = walk_forward(
        df, SpringADX25,
        {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="ADX > 25"
    )

    # SMA200 + ADX > 25
    wf_combo = walk_forward(
        df, SpringSMA200_ADX25,
        {"lookback": 30, "sma_period": 200, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="SMA200 + ADX > 25"
    )

    # PDI > MDI + ADX > 25
    wf_best = walk_forward(
        df, SpringPDIgtMDI_ADX25,
        {"lookback": 30, "stop_pct": 3.0, "target_pct": 1.5, "hold_hours": 6},
        n_splits=6, label="PDI > MDI + ADX > 25"
    )

    # Target sweep for best variant
    print("\n" + "=" * 70)
    print("  TARGET SWEEP (PDI > MDI + ADX > 25)")
    print("=" * 70)

    for target in [1.0, 1.2, 1.5, 2.0, 2.5]:
        strategy = SpringPDIgtMDI_ADX25({"lookback": 30, "stop_pct": 3.0, "target_pct": target, "hold_hours": 6})
        result = engine.run(
            df, strategy, symbol="BTC/USDT",
            stop_loss_pct=3.0, take_profit_pct=target, max_hold_bars=6,
        )
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  target={target:.1f}%  trades={m.total_trades:>4}  sharpe={m.sharpe_ratio:>6.2f}  "
              f"DD={m.max_drawdown_pct:>5.1f}%  WR={m.win_rate_pct:>5.1f}%  sum={lin_sum:>+7.1f}%")

    print("\n" + "=" * 70)
    print("  RESEARCH CONCLUSION")
    print("=" * 70)
    print("""
    KEY FINDINGS:
    1. Spring baseline with proper lows-based stops: Sharpe -0.65 (NOT 2.72)
    2. The documented Sharpe 2.72 used closes-based stops (incorrect)
    3. Regime analysis: PDI > MDI shows +8.9%, ADX > 25 shows +3.2%
    4. Directional filters may capture profitable regimes

    QUESTION: Do directional filters make Spring tradeable?
    - Need 4+/6 walk-forward splits profitable
    - Need Sharpe > 1.0 after filtering
    - Need sufficient trade count (>100 for statistical significance)
    """)


if __name__ == "__main__":
    main()
