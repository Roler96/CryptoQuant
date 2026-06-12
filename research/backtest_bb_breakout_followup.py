"""
VCB Follow-up: Simple BB Breakout (no compression filter) + tight parameters
=============================================================================
The main research showed compression_pctile=50% was best — meaning the
compression filter HURTS. This tests whether a simple BB breakout
(without requiring prior compression) has any edge.

Also tests: ultra-tight stops/targets, very short holds.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter
import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, ema, bollinger_bands


def simple_bb_breakout_signal(df, bb_period=20, bb_std=2.0, trend_filter="none", trend_period=200):
    """Simple: close > upper_band → long signal. No compression requirement."""
    close = df["close"]
    bb = bollinger_bands(df, period=bb_period, std=bb_std)
    
    long_signal = close > bb["upper"]
    
    if trend_filter == "sma200":
        trend_val = sma(close, trend_period)
        long_signal = long_signal & (close > trend_val)
    elif trend_filter == "ema50":
        trend_val = ema(close, trend_period)
        long_signal = long_signal & (close > trend_val)
    
    signal = pd.Series(0, index=df.index, dtype=int)
    signal[long_signal] = 1
    return signal


class SimpleBBBreakout(Strategy):
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 4}

    @property
    def name(self):
        return "SimpleBB"

    def generate_signal(self, df):
        df = self.preprocess(df)
        return simple_bb_breakout_signal(df, self.params["bb_period"], self.params["bb_std"])


class SimpleBBBreakoutSMA(Strategy):
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"bb_period": 20, "bb_std": 2.0, "trend_filter": "sma200", "trend_period": 200,
                      "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 4}

    @property
    def name(self):
        return "SimpleBB_SMA200"

    def generate_signal(self, df):
        df = self.preprocess(df)
        return simple_bb_breakout_signal(df, self.params["bb_period"], self.params["bb_std"],
                                         self.params["trend_filter"], self.params["trend_period"])


class BBLowerBounce(Strategy):
    """Counter-trend: buy when price touches LOWER BB (mean reversion)."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 2.0, "target_pct": 2.0, "hold_hours": 12}

    @property
    def name(self):
        return "BB_Lower_Bounce"

    def generate_signal(self, df):
        df = self.preprocess(df)
        close = df["close"]
        bb = bollinger_bands(df, period=self.params["bb_period"], std=self.params["bb_std"])
        # Buy when close touches or goes below lower band
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[close <= bb["lower"]] = 1
        return signal


class BBMiddleCross(Strategy):
    """Buy when price crosses above BB middle (20 SMA) from below."""
    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"
    DEFAULT_PARAMS = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 2.0, "target_pct": 3.0, "hold_hours": 12}

    @property
    def name(self):
        return "BB_Middle_Cross"

    def generate_signal(self, df):
        df = self.preprocess(df)
        close = df["close"]
        bb = bollinger_bands(df, period=self.params["bb_period"], std=self.params["bb_std"])
        middle = bb["middle"]
        # Cross above middle: current > middle AND previous <= middle
        cross_above = (close > middle) & (close.shift(1) <= middle.shift(1))
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[cross_above] = 1
        return signal


def walk_forward(df, strategy_cls, strategy_params, n_splits=6, label=""):
    n = len(df)
    slot = n // (n_splits + 2)
    results = []
    print(f"\n  WF: {label}")
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
            stop_loss_pct=strategy.params.get("stop_pct", 1.5),
            take_profit_pct=strategy.params.get("target_pct", 3.0),
            max_hold_bars=strategy.params.get("hold_hours", 4),
        )
        lin_sum = sum(t.pnl_pct for t in result.trades)
        sharpe = result.metrics.sharpe_ratio
        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        star = "⭐" if lin_sum > 0 else "  "
        print(f"    {star} {start_date}→{end_date}  trades={len(result.trades):>4}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}")
        results.append({"sum": lin_sum, "sharpe": sharpe})
    profitable = sum(1 for r in results if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    print(f"    → {profitable}/{len(results)} profitable, mean Sharpe: {mean_sharpe:+.2f}")
    return results


def main():
    print("=" * 70)
    print("  VCB FOLLOW-UP: Simple BB Breakout + Alternative BB Signals")
    print("=" * 70)

    store = OHLCVStore(db_path="data/cryptoquant.db")
    df = store.load("okx", "BTC/USDT", "1h")
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)

    # Test 1: Simple BB Breakout with various parameters
    print("\n" + "=" * 70)
    print("  TEST 1: Simple BB Breakout (no compression) — Parameter Grid")
    print("=" * 70)
    print(f"  {'Config':<35} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*80}")

    configs = [
        # (stop, target, hold, label)
        (1.0, 1.5, 4, "s1.0 t1.5 h4"),
        (1.0, 2.0, 4, "s1.0 t2.0 h4"),
        (1.0, 2.0, 8, "s1.0 t2.0 h8"),
        (1.0, 3.0, 4, "s1.0 t3.0 h4"),
        (1.5, 2.0, 4, "s1.5 t2.0 h4"),
        (1.5, 3.0, 4, "s1.5 t3.0 h4"),
        (1.5, 3.0, 8, "s1.5 t3.0 h8"),
        (1.5, 4.0, 4, "s1.5 t4.0 h4"),
        (2.0, 3.0, 4, "s2.0 t3.0 h4"),
        (2.0, 4.0, 8, "s2.0 t4.0 h8"),
        (2.0, 4.0, 12, "s2.0 t4.0 h12"),
        (2.0, 5.0, 12, "s2.0 t5.0 h12"),
        (2.0, 6.0, 24, "s2.0 t6.0 h24"),
    ]

    for stop, target, hold, label in configs:
        params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": stop, "target_pct": target, "hold_hours": hold}
        strategy = SimpleBBBreakout(params)
        result = engine.run(df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=stop, take_profit_pct=target, max_hold_bars=hold)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {label:<35} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    # Test 2: Simple BB Breakout + SMA200
    print("\n" + "=" * 70)
    print("  TEST 2: Simple BB Breakout + SMA200")
    print("=" * 70)
    print(f"  {'Config':<35} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*80}")

    for stop, target, hold, label in configs:
        params = {"bb_period": 20, "bb_std": 2.0, "trend_filter": "sma200", "trend_period": 200,
                  "stop_pct": stop, "target_pct": target, "hold_hours": hold}
        strategy = SimpleBBBreakoutSMA(params)
        result = engine.run(df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=stop, take_profit_pct=target, max_hold_bars=hold)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {label:<35} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    # Test 3: BB Lower Band Bounce (mean reversion)
    print("\n" + "=" * 70)
    print("  TEST 3: BB Lower Band Bounce (Mean Reversion)")
    print("=" * 70)
    print(f"  {'Config':<35} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*80}")

    bb_configs = [
        (1.5, 1.5, 6, "s1.5 t1.5 h6"),
        (1.5, 2.0, 6, "s1.5 t2.0 h6"),
        (2.0, 2.0, 8, "s2.0 t2.0 h8"),
        (2.0, 2.0, 12, "s2.0 t2.0 h12"),
        (2.0, 3.0, 12, "s2.0 t3.0 h12"),
        (2.5, 2.5, 12, "s2.5 t2.5 h12"),
        (3.0, 3.0, 24, "s3.0 t3.0 h24"),
        (3.0, 4.0, 24, "s3.0 t4.0 h24"),
    ]

    for stop, target, hold, label in bb_configs:
        params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": stop, "target_pct": target, "hold_hours": hold}
        strategy = BBLowerBounce(params)
        result = engine.run(df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=stop, take_profit_pct=target, max_hold_bars=hold)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {label:<35} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    # Test 4: BB Middle Line Cross
    print("\n" + "=" * 70)
    print("  TEST 4: BB Middle Line Cross (Trend Start)")
    print("=" * 70)
    print(f"  {'Config':<35} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*80}")

    for stop, target, hold, label in bb_configs:
        params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": stop, "target_pct": target, "hold_hours": hold}
        strategy = BBMiddleCross(params)
        result = engine.run(df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=stop, take_profit_pct=target, max_hold_bars=hold)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {label:<35} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    # Test 5: Walk-forward on best configurations
    print("\n" + "=" * 70)
    print("  TEST 5: WALK-FORWARD ON PROMISING VARIANTS")
    print("=" * 70)

    # Test BB Lower Bounce with best params
    best_bb_params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 2.0, "target_pct": 2.0, "hold_hours": 12}
    walk_forward(df, BBLowerBounce, best_bb_params, label="BB Lower Bounce s2 t2 h12")

    # Test Simple BB with best params
    best_simple_params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 1.5, "target_pct": 3.0, "hold_hours": 4}
    walk_forward(df, SimpleBBBreakout, best_simple_params, label="Simple BB s1.5 t3.0 h4")

    # Test BB Middle Cross
    best_cross_params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 2.0, "target_pct": 3.0, "hold_hours": 12}
    walk_forward(df, BBMiddleCross, best_cross_params, label="BB Middle Cross s2 t3 h12")

    # Test 6: BB std sensitivity (1.5 vs 2.0 vs 2.5)
    print("\n" + "=" * 70)
    print("  TEST 6: BB STD SENSITIVITY (Lower Bounce)")
    print("=" * 70)
    print(f"  {'BB_Std':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    for bb_std in [1.0, 1.5, 2.0, 2.5, 3.0]:
        params = {"bb_period": 20, "bb_std": bb_std, "stop_pct": 2.0, "target_pct": 2.0, "hold_hours": 12}
        strategy = BBLowerBounce(params)
        result = engine.run(df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=2.0, take_profit_pct=2.0, max_hold_bars=12)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {bb_std:>7.1f} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    # Test 7: BB period sensitivity
    print("\n" + "=" * 70)
    print("  TEST 7: BB PERIOD SENSITIVITY (Lower Bounce)")
    print("=" * 70)
    print(f"  {'Period':>8} {'Trades':>7} {'Sum':>8} {'Sharpe':>8} {'DD':>8} {'WR':>6} {'PF':>6}")
    print(f"  {'-'*55}")
    
    for period in [10, 15, 20, 30, 50]:
        params = {"bb_period": period, "bb_std": 2.0, "stop_pct": 2.0, "target_pct": 2.0, "hold_hours": 12}
        strategy = BBLowerBounce(params)
        result = engine.run(df, strategy, symbol="BTC/USDT",
                           stop_loss_pct=2.0, take_profit_pct=2.0, max_hold_bars=12)
        m = result.metrics
        lin_sum = sum(t.pnl_pct for t in result.trades)
        print(f"  {period:>7} {m.total_trades:>7} {lin_sum:>+7.1f}% {m.sharpe_ratio:>+8.2f} {m.max_drawdown_pct:>7.1f}% {m.win_rate_pct:>5.1f}% {m.profit_factor:>5.2f}")

    # Test 8: Detailed result on best BB Lower Bounce variant
    print("\n" + "=" * 70)
    print("  TEST 8: DETAILED — Best BB Lower Bounce")
    print("=" * 70)

    # Use 2.0/2.0/12 as baseline
    params = {"bb_period": 20, "bb_std": 2.0, "stop_pct": 2.0, "target_pct": 2.0, "hold_hours": 12}
    strategy = BBLowerBounce(params)
    result = engine.run(df, strategy, symbol="BTC/USDT",
                       stop_loss_pct=2.0, take_profit_pct=2.0, max_hold_bars=12)
    
    m = result.metrics
    trades = result.trades
    exits = Counter(t.exit_reason for t in trades)
    
    print(f"\n  BB Lower Bounce (s=2.0%, t=2.0%, h=12)")
    print(f"    Total Trades:       {m.total_trades}")
    print(f"    Compound Return:    {m.total_return_pct:+.1f}%")
    print(f"    Linear Sum:         {sum(t.pnl_pct for t in trades):+.1f}%")
    print(f"    Sharpe Ratio:       {m.sharpe_ratio:+.2f}")
    print(f"    Sortino Ratio:      {m.sortino_ratio:+.2f}")
    print(f"    Max Drawdown:       {m.max_drawdown_pct:.1f}%")
    print(f"    Win Rate:           {m.win_rate_pct:.1f}%")
    print(f"    Avg Win:            {m.avg_win_pct:+.3f}%")
    print(f"    Avg Loss:           {m.avg_loss_pct:+.3f}%")
    print(f"    Profit Factor:      {m.profit_factor:.2f}")
    print(f"\n    Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit"]:
        if reason in exits:
            subset = [t for t in trades if t.exit_reason == reason]
            avg_pnl = np.mean([t.pnl_pct for t in subset])
            total_pnl = sum(t.pnl_pct for t in subset)
            pct = len(subset) / len(trades) * 100
            print(f"      {reason:<16} {len(subset):>5} ({pct:>4.1f}%)  avg={avg_pnl:>+6.2f}%  total={total_pnl:>+8.1f}%")
    
    mfes = [t.mfe_pct for t in trades]
    maes = [t.mae_pct for t in trades]
    print(f"\n    MFE: mean={np.mean(mfes):+.2f}%  median={np.median(mfes):+.2f}%")
    print(f"    MAE: mean={np.mean(maes):+.2f}%  median={np.median(maes):+.2f}%")

    print("\n" + "=" * 70)
    print("  FOLLOW-UP RESEARCH COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
