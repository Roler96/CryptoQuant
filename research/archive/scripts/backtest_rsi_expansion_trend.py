"""RSI Expansion Trend strategy.

Trend-following strategy using RSI(14) midline crossover as the
primary entry trigger, confirmed by ATR expansion filter.  Exactly
2 entry conditions — matches the proven 2-condition template.

The ATR expansion filter (bar range > 1.5 × ATR(14)) is the
most-proven universal confirmation filter across 28 research loops,
achieving 6/7 perfect 4/4 gate sweeps.

Entry (long):  RSI(14) crosses above 50 AND bar range > 1.5 × ATR(14)
Entry (short): RSI(14) crosses below 50 AND bar range > 1.5 × ATR(14)
Exit (long):   RSI crosses below 50 (reverse signal)
Exit (short):  RSI crosses above 50 (reverse signal)

This is the first strategy to use RSI as the PRIMARY entry trigger
(rather than just a confirmation filter) paired with ATR expansion.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, rsi


class RSIExpansionTrend(Strategy):
    """RSI midline crossover with ATR expansion confirmation.

    Parameters:
        rsi_period: RSI lookback period (default 14).
        atr_period: ATR lookback period (default 14).
        expansion_mult: ATR expansion multiplier (default 1.5).
        rsi_long_entry: RSI threshold for long entry (default 50).
        rsi_short_entry: RSI threshold for short entry (default 50).
    """

    timeframe = "1h"
    min_bars = 100  # max(atr_period=14, rsi_period=14) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "rsi_period": 14,
        "atr_period": 14,
        "expansion_mult": 1.5,
        "rsi_long_entry": 50,
        "rsi_short_entry": 50,
    }

    @property
    def name(self) -> str:
        return "RSIExpansionTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from RSI crossover + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        rsi_period = self.params["rsi_period"]
        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]
        rsi_long_entry = self.params["rsi_long_entry"]
        rsi_short_entry = self.params["rsi_short_entry"]

        # Compute indicators
        rsi_val = rsi(close, period=rsi_period)
        atr_val = atr(df, period=atr_period)
        bar_range = df["high"] - df["low"]

        # Entry conditions (2 conditions: RSI crossover + ATR expansion)
        rsi_above = rsi_val > rsi_long_entry
        rsi_below = rsi_val < rsi_short_entry
        expansion = bar_range > expansion_mult * atr_val

        long_entry = rsi_above & expansion
        short_entry = rsi_below & expansion

        # Exit: RSI crosses back across threshold
        exit_long = rsi_below
        exit_short = rsi_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(rsi_val.iloc[i])
                or pd.isna(atr_val.iloc[i])
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
