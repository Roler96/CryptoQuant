"""Bollinger Band Squeeze Breakout strategy.

Volatility expansion strategy: detect BB width contraction (squeeze)
followed by a breakout outside the bands. Exactly 2 entry conditions.

BB width = (BB_upper - BB_lower) / BB_middle (normalized)
Squeeze: BB width at multi-period minimum

Entry (long):  squeeze detected AND close > BB_upper
Entry (short): squeeze detected AND close < BB_lower
Exit (long):   close < BB_middle (SMA20)
Exit (short):  close > BB_middle (SMA20)

The squeeze identifies quiet consolidation periods. When price breaks out
during a squeeze, it signals the start of a volatility expansion — the
beginning of a new directional move.

Reference: John Bollinger — "Bollinger on Bollinger Bands" (2001).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import bb_squeeze, bollinger_bands


class BBSqueezeBreakout(Strategy):
    """Bollinger Band Squeeze Breakout — volatility expansion entry.

    Parameters:
        bb_period: BB moving average period (default 20)
        bb_std: BB standard deviation multiplier (default 2.0)
        squeeze_lookback: Bars for minimum BB width detection (default 125)
    """

    timeframe = "1h"
    min_bars = 300  # squeeze_lookback + bb_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "squeeze_lookback": 125,
    }

    @property
    def name(self) -> str:
        return "BBSqueezeBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from BB squeeze + breakout.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        squeeze_lookback = self.params["squeeze_lookback"]

        # Compute indicators
        bands = bollinger_bands(df, period=bb_period, std=bb_std)
        upper = bands["upper"]
        lower = bands["lower"]
        middle = bands["middle"]

        is_squeeze = bb_squeeze(
            df,
            bb_period=bb_period,
            bb_std=bb_std,
            squeeze_lookback=squeeze_lookback,
        )

        # Entry signals (2 conditions: squeeze + breakout)
        long_entry = is_squeeze & (close > upper)
        short_entry = is_squeeze & (close < lower)

        # Exit signals: price crosses BB middle band (SMA20)
        exit_long = close < middle
        exit_short = close > middle

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(upper.iloc[i]) or pd.isna(lower.iloc[i]):
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
