"""Force Index Trend Following strategy.

Trend-following strategy using Elder's Force Index (volume-weighted
price momentum) crossover confirmed by an EMA200 trend filter.
Exactly 2 entry conditions.

Entry (long):  Force Index crosses ABOVE zero AND close > EMA200
Entry (short): Force Index crosses BELOW zero AND close < EMA200
Exit (long):   Force Index crosses BELOW zero
Exit (short):  Force Index crosses ABOVE zero

Force Index = EMA((Close_t - Close_t-1) × Volume_t, 13).  The volume
multiplication amplifies signals on high-conviction directional moves
and mutes noise from low-volume drift.  The 13-period EMA smoothing
reveals sustained buying/selling pressure.

Reference: Alexander Elder — "Trading for a Living" (1993).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, force_index


class ForceIndexTrend(Strategy):
    """Force Index zero-cross with EMA200 trend filter.

    Force Index measures the strength of buying/selling pressure by
    multiplying price change by volume and smoothing the result.  A
    zero-cross of the smoothed Force Index signals a shift in the
    dominant pressure direction.  Entry requires both the zero-cross
    AND price trend alignment (close vs EMA200).

    Parameters:
        fi_period: Force Index smoothing period (default 13)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period + FI warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "fi_period": 13,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ForceIndexTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Force Index zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        fi_period = self.params["fi_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        fi = force_index(df, period=fi_period)
        ema_trend = ema(close, period=trend_period)

        # Zero-cross detection
        fi_above_zero = fi > 0
        fi_below_zero = fi < 0
        prev_above = fi_above_zero.shift(1).fillna(False)
        prev_below = fi_below_zero.shift(1).fillna(False)

        cross_up = fi_above_zero & ~prev_above.astype(bool)
        cross_down = fi_below_zero & ~prev_below.astype(bool)

        # Entry signals (2 conditions: FI cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse FI zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(fi.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
