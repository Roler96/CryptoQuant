"""Inside Bar Breakout strategy.

A simplified price-action breakout strategy: enters when price breaks the
previous bar's range AND the breakout bar shows ATR-confirmed expansion.

Inside bar (compression): current_high < prev_high AND current_low > prev_low
Breakout (expansion): close breaks above prev_high or below prev_low
ATR confirmation: breakout bar range > ATR × expansion_mult

This is a 1-bar version of the channel breakout pattern — faster signals
than 20-bar Donchian/Lookback channels, compensated by the ATR expansion
filter to eliminate noise breakouts.

Entry (long):  Close > previous bar's high AND bar_range > ATR × multiplier
Entry (short): Close < previous bar's low AND bar_range > ATR × multiplier
Exit (long):   Close < previous bar's low (reverse breakout)
Exit (short):  Close > previous bar's high (reverse breakout)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr


class InsideBarBreakout(Strategy):
    """Inside Bar Breakout with ATR Expansion Confirmation.

    Parameters:
        atr_period: ATR lookback period (default 14)
        expansion_mult: Bar range must exceed ATR × M to confirm (default 1.5)
    """

    timeframe = "1h"
    min_bars = 60  # atr_period * 4
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "atr_period": 14,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "InsideBarBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from inside bar breakout with ATR confirmation.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]  # type: ignore[assignment]
        low: pd.Series = df["low"]  # type: ignore[assignment]

        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]

        # Previous bar's high/low (shifted: no look-ahead)
        prev_high = high.shift(1)
        prev_low = low.shift(1)

        # ATR for expansion confirmation
        atr_val = atr(df, period=atr_period)

        # Bar range
        bar_range = high - low

        # Expansion condition: current bar range exceeds ATR * multiplier
        expanding = bar_range > (atr_val * expansion_mult)

        # Entry signals (2 conditions: breakout + expansion)
        long_breakout = close > prev_high
        short_breakout = close < prev_low

        long_entry = long_breakout & expanding
        short_entry = short_breakout & expanding

        # Exit signals: price breaks opposite direction
        exit_long = close < prev_low
        exit_short = close > prev_high

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(prev_high.iloc[i]) or pd.isna(atr_val.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
