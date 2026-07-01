"""Choppiness-Filtered Donchian Breakout strategy.

Trend-following strategy using Donchian channel breakout confirmed
by Choppiness Index trending filter. Exactly 2 entry conditions.

The Choppiness Index measures whether the market is trending or
ranging. When CI < threshold (trending), the market has direction
and breakouts are more likely to follow through. When CI >= threshold
(choppy), breakouts tend to fail — we stay flat.

Entry (long):  close > Donchian upper AND CI < 38.2
Entry (short): close < Donchian lower AND CI < 38.2
Exit (long):   close < Donchian middle
Exit (short):  close > Donchian middle

Reference: E.W. Dreiss — "The Choppiness Index" (S&C, 1993).
Richard Donchian — Donchian Channel breakout methodology.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import choppiness_index, donchian


class ChoppinessBreakout(Strategy):
    """Choppiness-filtered Donchian breakout.

    Entry requires price to break the Donchian channel AND the
    Choppiness Index to indicate trending conditions (< threshold).
    Two conditions total.

    Parameters:
        channel_period: Donchian channel lookback (default 20).
        ci_period: Choppiness Index lookback (default 14).
        ci_threshold: CI below this = trending (default 38.2).
    """

    timeframe = "1h"
    min_bars = 230  # max(channel_period, ci_period) * 2 + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "channel_period": 20,
        "ci_period": 14,
        "ci_threshold": 38.2,
    }

    @property
    def name(self) -> str:
        return "ChoppinessBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Donchian breakout + Choppiness filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        channel_period = self.params["channel_period"]
        ci_period = self.params["ci_period"]
        ci_threshold = self.params["ci_threshold"]

        # Compute indicators
        dc = donchian(df, period=channel_period)
        upper = dc["upper"]
        lower = dc["lower"]
        middle = dc["middle"]
        ci = choppiness_index(df, period=ci_period)

        # Entry: price breaks channel + market is trending (CI < threshold)
        is_trending = ci < ci_threshold

        long_entry = (close > upper) & is_trending
        short_entry = (close < lower) & is_trending

        # Exit: close crosses back across middle of channel
        exit_long = close < middle
        exit_short = close > middle

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(upper.iloc[i]) or pd.isna(lower.iloc[i]) or pd.isna(middle.iloc[i]) or pd.isna(ci.iloc[i]):
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
