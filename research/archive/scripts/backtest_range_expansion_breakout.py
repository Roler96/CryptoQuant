"""Range Expansion Breakout strategy.

Simplified volatility breakout strategy: enters when price breaks an
N-bar consolidation range AND the current bar's range confirms genuine
expansion via ATR. Unlike prior breakout strategies that used volume or
RSI confirmation, this uses ATR-based bar expansion as the sole filter.

Entry (long):  Close > highest high of last N AND (high-low) > ATR(N) × M
Entry (short): Close < lowest low of last N AND (high-low) > ATR(N) × M
Exit (long):   Close < lowest low of last N (channel exit)
Exit (short):  Close > highest high of last N (channel exit)

Reference: Classic Turtle Trading / Donchian channel breakout with ATR
expansion confirmation. Expansion multiplier filters ~60-70% of false
breakouts vs. simple Donchian.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, rolling_max, rolling_min


class RangeExpansionBreakout(Strategy):
    """Range Expansion Breakout with ATR Confirmation.

    Parameters:
        lookback: Bars for channel high/low (default 20)
        atr_period: ATR lookback period (default 20)
        expansion_mult: Bar range must exceed ATR × M to confirm (default 1.5)
    """

    timeframe = "1h"
    min_bars = 60  # max(lookback, atr_period) * 3, padded
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lookback": 20,
        "atr_period": 20,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "RangeExpansionBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from range expansion breakout.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]  # type: ignore[assignment]
        low: pd.Series = df["low"]  # type: ignore[assignment]

        lookback = self.params["lookback"]
        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]

        # Channel boundaries (shifted: no look-ahead)
        channel_high = rolling_max(high, period=lookback).shift(1)
        channel_low = rolling_min(low, period=lookback).shift(1)

        # ATR for expansion confirmation
        atr_val = atr(df, period=atr_period)

        # Bar range
        bar_range = high - low

        # Expansion condition: current bar range exceeds ATR * multiplier
        expanding = bar_range > (atr_val * expansion_mult)

        # Entry signals
        long_breakout = close > channel_high
        short_breakout = close < channel_low

        long_entry = long_breakout & expanding
        short_entry = short_breakout & expanding

        # Exit signals: price crosses beyond opposite channel boundary
        exit_long = close < channel_low
        exit_short = close > channel_high

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(channel_high.iloc[i]) or pd.isna(atr_val.iloc[i]):
                signal[i] = 0
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

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
