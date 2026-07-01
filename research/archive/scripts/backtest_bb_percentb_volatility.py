"""Bollinger %B Volatility Expansion strategy.

Breakout strategy using Bollinger %B threshold crossing confirmed by
ATR expansion. Exactly 2 entry conditions.

Entry (long):  %B > 0.8 (strong upper band push) AND ATR expanding
Entry (short): %B < 0.2 (strong lower band push) AND ATR expanding
Exit (long):   %B < 0.5 (price retreats below band midline)
Exit (short):  %B > 0.5 (price recovers above band midline)

ATR expansion confirmation (ATR > rolling mean of ATR) is proven
superior to volume confirmation for breakout strategies (Loop 5
meta-analysis: ATR > RSI > Volume). The %B approach is more
nuanced than raw price pierce — it measures HOW FAR price is
through the band, filtering marginal pierces.

Reference: John Bollinger — "Bollinger on Bollinger Bands" (2002).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, bollinger_bands, sma


class BBPercentBVolatility(Strategy):
    """Bollinger %B breakout with ATR expansion confirmation.

    Entry requires %B above/below threshold AND ATR expanding.
    Exit when %B retreats below band midline.

    Parameters:
        bb_period: Bollinger Band SMA period (default 20)
        bb_std: Standard deviation multiplier (default 2.0)
        percent_b_entry: %B threshold for entry (default 0.8)
        percent_b_short_entry: %B threshold for short entry (default 0.2)
        percent_b_exit: %B threshold for exit (default 0.5)
        atr_period: ATR period for expansion check (default 14)
        atr_ma_period: SMA period for ATR baseline (default 50)
    """

    timeframe = "1h"
    min_bars = 100  # max(bb_period, atr_ma_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "percent_b_entry": 0.8,
        "percent_b_short_entry": 0.2,
        "percent_b_exit": 0.5,
        "atr_period": 14,
        "atr_ma_period": 50,
    }

    @property
    def name(self) -> str:
        return "BBPercentBVolatility"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from %B thresholds + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        pct_b_entry = self.params["percent_b_entry"]
        pct_b_short = self.params["percent_b_short_entry"]
        pct_b_exit = self.params["percent_b_exit"]
        atr_period = self.params["atr_period"]
        atr_ma_period = self.params["atr_ma_period"]

        # Compute indicators
        bb = bollinger_bands(df, period=bb_period, std=bb_std)
        percent_b: pd.Series = bb["pct_b"]  # type: ignore[assignment]
        atr_val = atr(df, period=atr_period)
        atr_ma = sma(atr_val, period=atr_ma_period)
        atr_expanding = atr_val > atr_ma

        # Entry signals (2 conditions: %B threshold + ATR expanding)
        long_entry = (percent_b > pct_b_entry) & atr_expanding
        short_entry = (percent_b < pct_b_short) & atr_expanding

        # Exit signals: %B crosses below/above midline
        exit_long = percent_b < pct_b_exit
        exit_short = percent_b > pct_b_exit

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(percent_b.iloc[i]) or pd.isna(atr_expanding.iloc[i]):
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
