"""Vortex Trend strategy.

Uses Vortex Indicator (VI+/VI-) crossover confirmed by EMA200 trend
filter. Exactly 2 entry conditions.

Entry (long):  VI+ > VI- AND Close > EMA(200)
Entry (short): VI- > VI+ AND Close < EMA(200)
Exit:          VI reverse crossover

The Vortex Indicator measures directional trend strength using price
extremes across bars (not within-bar), normalized by true range.
Unlike smoothed oscillators (RSI, Stochastic), VI uses raw rolling sums
with no exponential smoothing — preserving signal frequency.

Reference: Etzkorn (2010), "The Vortex Indicator".
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, vortex


class VortexTrend(Strategy):
    """Vortex crossover with EMA200 trend filter.

    Entry requires VI+ crosses above VI- (long) / VI- crosses above VI+
    (short) AND EMA200 directional alignment.

    Parameters:
        vi_period: Vortex Indicator lookback period (default 14)
        trend_period: Period for trend filter EMA (default 200)
    """

    timeframe = "1h"
    min_bars = 215  # vi_period + trend_period + margin
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "vi_period": 14,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "VortexTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Vortex crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        vi_period = self.params["vi_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        vi = vortex(df, period=vi_period)
        vip = vi["vip"]
        vim = vi["vim"]

        # Entry signals: 2 conditions (VI crossover + trend filter)
        long_entry = (vip > vim) & (close > ema_trend)
        short_entry = (vim > vip) & (close < ema_trend)

        # Exit: reverse crossover
        exit_long = vip <= vim
        exit_short = vim <= vip

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(vip.iloc[i]):
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
