"""ATR Breakout with Trend Filter — volatility expansion trend follower.

ATRBreakout with an EMA trend filter: only enter in the direction of the
longer-term trend. Reduces counter-trend whipsaws while preserving the
core breakout logic.

Entry (long):  close > 20-bar high AND bar_range > 1.5 × ATR(14) AND close > EMA(N)
Entry (short): close < 20-bar low AND bar_range > 1.5 × ATR(14) AND close < EMA(N)
Exit: signal reverse (close crosses channel opposite side)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, ema


class ATRBreakoutTrend(Strategy):
    """ATR expansion breakout with EMA trend filter."""

    timeframe = "5m"
    min_bars = 200
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "channel_period": 20,
        "atr_period": 14,
        "expansion_mult": 1.5,
        "trend_ema": 200,
    }

    @property
    def name(self) -> str:
        return "ATRBreakoutTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        high: pd.Series = df["high"]
        low: pd.Series = df["low"]
        close: pd.Series = df["close"]

        cp = self.params["channel_period"]
        ap = self.params["atr_period"]
        em = self.params["expansion_mult"]
        trend_period = self.params["trend_ema"]

        atr_val = atr(df, period=ap).shift(1)
        bar_range = high - low
        channel_high = high.rolling(cp).max().shift(1)
        channel_low = low.rolling(cp).min().shift(1)
        trend_ema_val = ema(close, period=trend_period).shift(1)

        expansion = bar_range > em * atr_val
        valid = ~(atr_val.isna() | channel_high.isna() | trend_ema_val.isna())

        # Trend filter: only go long above EMA, short below EMA
        long_entry = (
            (close > channel_high) & expansion & (close > trend_ema_val) & valid
        )
        short_entry = (
            (close < channel_low) & expansion & (close < trend_ema_val) & valid
        )

        # Exit: price crosses to opposite side of channel
        exit_long = close < channel_low
        exit_short = close > channel_high

        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if not valid.iloc[i]:
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
