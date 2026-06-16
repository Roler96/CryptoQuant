"""
Out-of-Sample Lockbox Demo — WickInversion
============================================
Demonstrates T2 ``split_train_test`` on the WickInversion strategy.

1. Loads OKX BTC/USDT 1h data from SQLite.
2. Splits into 80/20 simple hold-out.
3. Runs walk-forward with 5 expanding-window splits.
4. Prints train/test sizes and backtest Sharpe per fold.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptoquant.data.oos import split_train_test
from cryptoquant.data.store import OHLCVStore
from cryptoquant.engine.backtest import BacktestEngine
from strategies.wick import WickInversion


def evaluate_fold(train_df, test_df, label):
    """Fit on train, evaluate on test."""
    strategy = WickInversion()
    engine = BacktestEngine(commission=0.0005, slippage=0.0005)
    result = engine.run(
        test_df,
        strategy,
        symbol="BTC/USDT",
        stop_loss_pct=strategy.params["stop_pct"],
        take_profit_pct=strategy.params["target_pct"],
        max_hold_bars=strategy.params["hold_hours"],
    )
    sharpe = result.metrics.sharpe_ratio
    trades = len(result.trades)
    print(f"  {label:20s}  train={len(train_df):>6d}  test={len(test_df):>6d}  "
          f"trades={trades:>4d}  sharpe={sharpe:+.2f}")
    return result


def main():
    print("=" * 70)
    print("  T2 OUT-OF-SAMPLE LOCKBOX — WickInversion")
    print("=" * 70)

    store = OHLCVStore()
    df = store.load("okx", "BTC/USDT", "1h")
    print(f"\nLoaded {len(df)} bars  ({df.index[0]} → {df.index[-1]})")

    # ------------------------------------------------------------------
    # 1. Simple 80/20 chronological split
    # ------------------------------------------------------------------
    print("\n--- Simple 80/20 Split ---")
    train, test = split_train_test(df, test_frac=0.2, method="simple")
    evaluate_fold(train, test, "Simple Hold-out")

    # ------------------------------------------------------------------
    # 2. Walk-forward expanding window (5 splits)
    # ------------------------------------------------------------------
    print("\n--- Walk-Forward Expanding Window (5 splits) ---")
    folds = split_train_test(df, method="walk_forward", n_splits=5)
    for i, (train, test) in enumerate(folds, start=1):
        evaluate_fold(train, test, f"Fold {i}")

    print("\n" + "=" * 70)
    print("  DEMO COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
