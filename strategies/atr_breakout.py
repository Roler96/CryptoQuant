"""ATR Breakout — simple volatility expansion trend follower for 5m.

Minimalist 2-condition breakout: close > 20-bar high AND ATR expansion.
No oscillators, no Hurst, no SMA — pure price action + volatility.
Designed to avoid the commission fragility of indicator-heavy strategies.

Entry (long):  close > 20-bar high AND bar_range > 1.5 × ATR(14)
Entry (short): close < 20-bar low AND bar_range > 1.5 × ATR(14)
Exit (long):   close < 20-bar low
Exit (short):  close > 20-bar high
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr


class ATRBreakout(Strategy):
    """Simple ATR expansion breakout."""

    timeframe = "5m"
    min_bars = 100
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "channel_period": 20,
        "atr_period": 14,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "ATRBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        high: pd.Series = df["high"]
        low: pd.Series = df["low"]
        close: pd.Series = df["close"]

        cp = self.params["channel_period"]
        ap = self.params["atr_period"]
        em = self.params["expansion_mult"]

        atr_val = atr(df, period=ap).shift(1)  # exclude current bar from ATR
        bar_range = high - low
        channel_high = high.rolling(cp).max().shift(1)
        channel_low = low.rolling(cp).min().shift(1)

        expansion = bar_range > em * atr_val
        valid = ~(atr_val.isna() | channel_high.isna())

        long_entry = (close > channel_high) & expansion & valid
        short_entry = (close < channel_low) & expansion & valid

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
