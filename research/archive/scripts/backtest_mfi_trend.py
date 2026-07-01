"""MFI Trend strategy.

Trend-following strategy using Money Flow Index (MFI) threshold crossover
with EMA200 trend direction filter.  Exactly 2 entry conditions.

MFI is a volume-weighted RSI oscillator normalized to 0-100.  Unlike Force
Index (unbounded), MFI's normalization makes it timeframe/symbol agnostic —
the same threshold works across all combos.  This is the key property that
made BB %B universally robust in Loop 11.

Entry (long):  MFI crosses above 50 AND close > EMA200
Entry (short): MFI crosses below 50 AND close < EMA200
Exit:          MFI crosses back through 50 (reverse signal)

Reference: Gene Quong & Avrum Soudack (1989).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, mfi, crossover, crossunder


class MfiTrend(Strategy):
    """MFI threshold crossover with EMA200 trend filter.

    Uses Money Flow Index — volume-weighted momentum oscillator (0-100).
    MFI crossing the 50 midline is the primary trigger; EMA200 provides
    directional confirmation.  2 conditions.

    Parameters:
        mfi_period: MFI calculation period (default 14).
        mfi_threshold: MFI midline threshold (default 50).
        trend_period: EMA period for trend direction filter (default 200).
    """

    timeframe = "1h"
    min_bars = 220  # trend_period + mfi warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "mfi_period": 14,
        "mfi_threshold": 50,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "MfiTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from MFI threshold crossover + EMA200 direction.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        mfi_period = self.params["mfi_period"]
        mfi_threshold = self.params["mfi_threshold"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        mfi_line = mfi(df, period=mfi_period)
        trend_line = ema(close, period=trend_period)

        # Build a constant threshold series for crossover utilities
        threshold = pd.Series(mfi_threshold, index=df.index, dtype=float)

        # Entry signals (2 conditions: MFI crosses 50 + trend direction)
        long_entry = (
            crossover(mfi_line, threshold).astype(bool)
            & (close > trend_line)
        )
        short_entry = (
            crossunder(mfi_line, threshold).astype(bool)
            & (close < trend_line)
        )

        # Exit signals: MFI crosses back through 50 (reverse signal)
        exit_long = crossunder(mfi_line, threshold).astype(bool)
        exit_short = crossover(mfi_line, threshold).astype(bool)

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(mfi_line.iloc[i]) or pd.isna(trend_line.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip to short
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip to long
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
