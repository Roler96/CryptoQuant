"""TRIX Trend strategy.

Trend-following strategy using TRIX (Triple Exponential Average) crossover
with its signal line, confirmed by EMA200 trend direction filter.
Exactly 2 entry conditions.

TRIX applies triple EMA smoothing before computing rate of change,
producing a very smooth oscillator that reveals genuine trend changes
while filtering crypto microstructure noise.

Entry (long):  TRIX crosses above Signal AND close > EMA200
Entry (short): TRIX crosses below Signal AND close < EMA200
Exit:          TRIX crosses back below/above Signal (reverse signal)

Reference: Jack Hutson — "Good Trix" (Stocks & Commodities, 1983).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, trix, crossover, crossunder


class TriXTrend(Strategy):
    """TRIX crossover with signal line and EMA200 trend filter.

    Uses TRIX — a triple-exponentially-smoothed rate-of-change oscillator.
    TRIX/Signal crossover is the primary trigger; EMA200 provides
    directional confirmation.  2 conditions.

    Parameters:
        trix_period: TRIX calculation period (default 15).
        signal_period: Signal line SMA period (default 9).
        trend_period: EMA period for trend direction filter (default 200).
    """

    timeframe = "1h"
    min_bars = 230  # trend_period + trix warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "trix_period": 15,
        "signal_period": 9,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "TriXTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TRIX crossover + EMA200 direction.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        trix_period = self.params["trix_period"]
        signal_period = self.params["signal_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        trix_df = trix(
            close,
            period=trix_period,
            signal_period=signal_period,
        )
        trix_line: pd.Series = trix_df["trix"]  # type: ignore[assignment]
        signal_line: pd.Series = trix_df["signal"]  # type: ignore[assignment]
        trend_line = ema(close, period=trend_period)

        # Entry signals (2 conditions: TRIX/Signal cross + trend direction)
        long_entry = (
            crossover(trix_line, signal_line).astype(bool)
            & (close > trend_line)
        )
        short_entry = (
            crossunder(trix_line, signal_line).astype(bool)
            & (close < trend_line)
        )

        # Exit signals: reverse crossover
        exit_long = crossunder(trix_line, signal_line).astype(bool)
        exit_short = crossover(trix_line, signal_line).astype(bool)

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(trix_line.iloc[i])
                or pd.isna(signal_line.iloc[i])
                or pd.isna(trend_line.iloc[i])
            ):
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
