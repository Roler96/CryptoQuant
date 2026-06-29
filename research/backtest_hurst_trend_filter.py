"""Hurst Trend Filter strategy.

Trend-following strategy using Hurst exponent (R/S analysis) as a
statistical persistence filter combined with EMA50 trend confirmation.
The Hurst exponent measures whether the market exhibits trending
(H > 0.5) or mean-reverting (H < 0.5) behaviour, filtering entries
to trending-only regimes.  Exactly 2 entry conditions.

Entry (long):  close crosses ABOVE EMA50 AND Hurst(100) > 0.55
Entry (short): close crosses BELOW EMA50 AND Hurst(100) > 0.55
Exit (long):   close crosses BELOW EMA50 OR Hurst(100) < 0.45
Exit (short):  close crosses ABOVE EMA50 OR Hurst(100) < 0.45
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, hurst_exponent


class HurstTrendFilter(Strategy):
    """Hurst exponent regime filter with EMA50 crossover.

    The Hurst exponent (H) is a fractal persistence measure:
      - H > 0.5 → trending (moves reinforce)
      - H < 0.5 → mean-reverting (moves reverse)

    By requiring H > 0.55 for entry, the strategy only trades when
    the time series exhibits genuine trending behaviour.  The EMA50
    crossover provides the timing signal within that regime.

    Parameters:
        ema_period: EMA trend reference lookback (default 50)
        hurst_period: Rolling window for R/S analysis (default 100)
        hurst_threshold: Minimum Hurst for entry (default 0.55)
        hurst_exit: Hurst floor for exit (default 0.45)
    """

    timeframe = "1h"
    min_bars = 100  # hurst_period warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ema_period": 50,
        "hurst_period": 100,
        "hurst_threshold": 0.55,
        "hurst_exit": 0.45,
    }

    @property
    def name(self) -> str:
        return "HurstTrendFilter"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Hurst regime + EMA crossover.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        ema_period = self.params["ema_period"]
        hurst_period = self.params["hurst_period"]
        hurst_threshold = self.params["hurst_threshold"]
        hurst_exit = self.params["hurst_exit"]

        # Compute indicators
        ema_trend = ema(close, period=ema_period)
        h = hurst_exponent(close, period=hurst_period)

        # Crossover detection
        above_ema = close > ema_trend
        below_ema = close < ema_trend
        prev_above = above_ema.shift(1).fillna(False)
        prev_below = below_ema.shift(1).fillna(False)

        cross_up = above_ema & ~prev_above.astype(bool)
        cross_down = below_ema & ~prev_below.astype(bool)

        # Hurst conditions
        h_trending = h > hurst_threshold
        h_lost = h < hurst_exit
        h_valid = ~h.isna()

        # Entry (2 conditions: EMA cross + Hurst trending)
        long_entry = cross_up & h_trending & h_valid
        short_entry = cross_down & h_trending & h_valid

        # Exit
        exit_long = cross_down | h_lost
        exit_short = cross_up | h_lost

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(h.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
