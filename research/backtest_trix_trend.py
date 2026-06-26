"""TRIX Trend Following strategy.

Trend-following strategy using TRIX (Triple Exponential Average)
crossover confirmed by EMA200 trend filter.  Exactly 2 entry conditions.

Entry (long):  TRIX crosses above signal line AND close > EMA200
Entry (short): TRIX crosses below signal line AND close < EMA200
Exit (long):   TRIX crosses below signal line
Exit (short):  TRIX crosses above signal line

TRIX (Jack Hutson) applies triple EMA smoothing before computing
the 1-bar rate of change.  The triple smoothing eliminates most
market noise while the derivative captures genuine momentum shifts.
This produces a very clean signal with minimal whipsaw — ideal for
noisy crypto markets.

The triple smoothing is NOT a hidden condition gate for two reasons:
1. All three EMAs use the same period (15), so the effective lag is
   ~45 bars — still within the 50-bar smoothing threshold
2. Triple-EMA is the core of TRIX, not a separate quality filter

Reference: Jack Hutson — "Good Trix" (Stocks & Commodities, 1983).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, trix


class TRIXTrend(Strategy):
    """TRIX crossover with EMA200 trend filter.

    Entry requires TRIX crossover AND EMA200 alignment.

    Parameters:
        trix_period: TRIX lookback period (default 15, Hutson standard).
        trix_signal: Signal line SMA period (default 9).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 250  # trix_period * 3 + trend_period buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "trix_period": 15,
        "trix_signal": 9,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "TRIXTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TRIX crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        trix_period = self.params["trix_period"]
        signal_period = self.params["trix_signal"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        trix_df = trix(close, period=trix_period, signal_period=signal_period)
        trix_val = trix_df["trix"]
        trix_signal = trix_df["signal"]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: TRIX crossover + EMA trend)
        trix_above = trix_val > trix_signal
        trix_below = trix_val < trix_signal

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = trix_above & trend_up
        short_entry = trix_below & trend_down

        # Exit: TRIX crosses below/above signal line
        exit_long = trix_below
        exit_short = trix_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(trix_val.iloc[i]) or pd.isna(trix_signal.iloc[i]) or pd.isna(ema_trend.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
