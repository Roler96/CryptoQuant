"""Bollinger Band Squeeze Breakout strategy.

Volatility-breakout strategy that waits for BB width contraction
(squeeze), then enters on a breakout of the bands. Exactly 2 entry
conditions: (1) squeeze detected, (2) price breakout.

BB squeeze occurs when BB width reaches a multi-period minimum,
signalling low-volatility consolidation. When price subsequently
breaks the bands, it often starts a volatility expansion (new trend).

Entry (long):  squeeze AND close > BB upper
Entry (short): squeeze AND close < BB lower
Exit (long):   close < BB middle (SMA20)
Exit (short):  close > BB middle (SMA20)

Reference: John Bollinger — "Bollinger on Bollinger Bands" (2001).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import bb_squeeze, bollinger_bands


class BBSqueezeBreakout(Strategy):
    """Bollinger Band Squeeze + Breakout strategy.

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

        # Compute BB and squeeze detection
        bb = bollinger_bands(df, period=bb_period, std=bb_std)
        bb_middle = bb["middle"]
        bb_upper = bb["upper"]
        bb_lower = bb["lower"]

        is_squeeze = bb_squeeze(
            df, bb_period=bb_period, bb_std=bb_std,
            squeeze_lookback=squeeze_lookback,
        )

        # Entry signals (2 conditions: squeeze + breakout)
        long_entry = is_squeeze & (close > bb_upper)
        short_entry = is_squeeze & (close < bb_lower)

        # Exit signals: price crosses back through middle band
        exit_long = close < bb_middle
        exit_short = close > bb_middle

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(bb_middle.iloc[i]):
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
