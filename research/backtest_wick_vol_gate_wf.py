"""
Quick walk-forward validation for optimized Wick Vol Gate config.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.strategy.signals import (
    atr as atr_func, wick_imbalance, pct_change_rolling
)
from cryptoquant.strategy.base import Strategy


class WickVolGateOpt(Strategy):
    """Wick + vol gate — optimized exits s3.0/t2.5/h16"""
    timeframe = "1h"
    min_bars = 300
    version = "vol_gate_opt"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.25,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 2.5,
        "hold_hours": 16,
    }

    @property
    def name(self) -> str:
        return "Wick_VolGate_Opt"

    def generate_signal(self, df):
        df = self.preprocess(df)
        imb = wick_imbalance(df, window=6)
        price_chg = pct_change_rolling(df["close"], 6)
        signal = (imb > 0.25) & (price_chg > -0.5)
        atr14 = atr_func(df, 14)
        median_atr = atr14.rolling(200).median()
        signal = signal & (atr14 / median_atr > 1.0)
        return signal.astype(int)


def main():
    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")

    # Full backtest
    strategy = WickVolGateOpt()
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    result = engine.run(df, strategy, symbol="BTC/USDT",
                       stop_loss_pct=3.0, take_profit_pct=2.5, max_hold_bars=16)

    m = result.metrics
    trades = result.trades

    # Exit breakdown
    exit_counts = {}
    exit_pnls = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
        if t.exit_reason not in exit_pnls:
            exit_pnls[t.exit_reason] = []
        exit_pnls[t.exit_reason].append(t.pnl_pct)

    print("=" * 60)
    print("  Wick Vol Gate OPTIMIZED — Full Backtest")
    print("  s3.0%, t2.5%, h16h, ATR > median")
    print("=" * 60)
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

    print(f"\n  Exit Breakdown:")
    for reason in ["take_profit", "stop_loss", "time_exit", "signal_reverse"]:
        count = exit_counts.get(reason, 0)
        pnl_list = exit_pnls.get(reason, [0])
        avg_pnl = np.mean(pnl_list) if pnl_list else 0
        total_pnl = sum(pnl_list)
        pct = count / len(trades) * 100 if trades else 0
        print(f"    {reason:15s} {count:>4d} ({pct:>4.1f}%)  avg={avg_pnl:>+7.3f}%  total={total_pnl:>+8.1f}%")

    # Walk-forward
    print(f"\n{'='*60}")
    print(f"  WALK-FORWARD (6 splits)")
    print(f"{'='*60}")

    n = len(df)
    slot = n // 8
    results = []
    for s in range(6):
        start_idx = n - (6 - s + 1) * slot
        end_idx = min(n, start_idx + slot)
        split_df = df.iloc[start_idx:end_idx].copy()
        if len(split_df) < 300:
            continue
        strategy = WickVolGateOpt()
        engine = BacktestEngine(commission=0.0005, slippage=0.0005)
        r = engine.run(split_df, strategy, symbol="BTC/USDT",
                      stop_loss_pct=3.0, take_profit_pct=2.5, max_hold_bars=16)
        lin_sum = sum(t.pnl_pct for t in r.trades)
        sharpe = r.metrics.sharpe_ratio
        start_date = pd.Timestamp(split_df.index[0]).strftime("%Y-%m")
        end_date = pd.Timestamp(split_df.index[-1]).strftime("%Y-%m")
        status = "✅" if lin_sum > 0 else "❌"
        print(f"  Split {s+1}: {start_date}→{end_date}  trades={len(r.trades):>4d}  sum={lin_sum:>+7.1f}%  sharpe={sharpe:>+6.2f}  {status}")
        results.append({"sum": lin_sum, "sharpe": sharpe, "trades": len(r.trades)})

    profitable = sum(1 for r in results if r["sum"] > 0)
    mean_sharpe = np.mean([r["sharpe"] for r in results]) if results else 0
    total_sum = sum(r["sum"] for r in results)
    print(f"\n  → {profitable}/6 OOS profitable | Mean OOS Sharpe: {mean_sharpe:+.2f} | Total OOS Sum: {total_sum:+.1f}%")


if __name__ == "__main__":
    main()
