"""VWAP + ATR Expansion Trend strategy.

Trend-following strategy using VWAP crossover as the primary entry
trigger, confirmed by ATR expansion filter.  Exactly 2 entry conditions
— matches the proven 2-condition template.

VWAP acts as a volume-weighted fair-value benchmark. Price crossing
above VWAP signals institutional buying pressure; ATR expansion
confirms genuine directional intent.  Unlike breakout-based entries,
VWAP crosses frequently enough to preserve the 50-200 trade/year
sweet spot.

Entry (long):  close crosses above VWAP(20) AND bar range > 1.5 × ATR(14)
Entry (short): close crosses below VWAP(20) AND bar range > 1.5 × ATR(14)
Exit (long):   close crosses below VWAP (reverse cross)
Exit (short):  close crosses above VWAP (reverse cross)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, vwap


class VWAPATRTrend(Strategy):
    """VWAP crossover with ATR expansion confirmation.

    Parameters:
        vwap_period: VWAP rolling window (default 20).
        atr_period: ATR lookback period (default 14).
        expansion_mult: ATR expansion multiplier (default 1.5).
    """

    timeframe = "1h"
    min_bars = 100  # max(vwap_period=20, atr_period=14) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "vwap_period": 20,
        "atr_period": 14,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "VWAPATRTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from VWAP crossover + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        vwap_period = self.params["vwap_period"]
        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]

        # Compute indicators
        vwap_val = vwap(df, period=vwap_period)
        atr_val = atr(df, period=atr_period)
        bar_range = df["high"] - df["low"]

        # Entry conditions (2 conditions: VWAP cross + ATR expansion)
        close_above_vwap = close > vwap_val
        close_below_vwap = close < vwap_val
        expansion = bar_range > expansion_mult * atr_val

        long_entry = close_above_vwap & expansion
        short_entry = close_below_vwap & expansion

        # Exit: close crosses back across VWAP
        exit_long = close_below_vwap
        exit_short = close_above_vwap

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(vwap_val.iloc[i]) or pd.isna(atr_val.iloc[i]):
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
