"""Decycler Trend — Ehlers Decycler Crossover + Trend Filter.

Trend-following strategy using Ehlers Decycler crossover with its
trigger line (Decycler lagged 1 bar), confirmed by EMA200 trend
direction. Exactly 2 entry conditions.

The Decycler (Ehlers, 2004) extracts the trend component from price
by removing cycles shorter than the cutoff period using a 2-pole
Butterworth low-pass filter. This is frequency-domain filtering —
fundamentally different from all time-domain moving averages tested
across previous loops.

Entry (long):  Decycler > Decycler.shift(1) AND close > EMA200
Entry (short): Decycler < Decycler.shift(1) AND close < EMA200
Exit (long):   Decycler < Decycler.shift(1) (reverse crossover)
Exit (short):  Decycler > Decycler.shift(1) (reverse crossover)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import decycler, ema


class DecyclerTrend(Strategy):
    """Ehlers Decycler crossover with EMA200 trend filter.

    The Decycler uses a 2-pole Butterworth low-pass filter to
    extract the trend component with near-zero phase lag. The
    crossover with its own 1-bar-lagged trigger line generates
    entry/exit signals. This is the first DSP-based indicator
    tested in the research pipeline.

    Parameters:
        cutoff_period: Decycler cutoff period in bars (default 20).
            Cycles shorter than this are attenuated.
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 235  # max(cutoff_period, trend_period) + 35
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "cutoff_period": 20,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "DecyclerTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Decycler crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        cutoff_period = self.params["cutoff_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        dc = decycler(close, cutoff_period=cutoff_period)
        trigger = dc.shift(1)  # Decycler lagged 1 bar (Ehlers' standard)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: Decycler crossover + trend filter)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        dc_cross_up = dc > trigger
        dc_cross_down = dc < trigger

        long_entry = trend_up & dc_cross_up
        short_entry = trend_down & dc_cross_down

        # Exit: Decycler reverse crossover
        exit_long = dc_cross_down
        exit_short = dc_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(dc.iloc[i])
                or pd.isna(trigger.iloc[i])
                or pd.isna(ema_trend.iloc[i])
            ):
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
