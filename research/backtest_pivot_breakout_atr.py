"""Pivot Breakout ATR strategy.

Breakout strategy using swing pivot points (structural market levels)
as reference levels, combined with ATR expansion confirmation.  Pivot
points are confirmed swing highs/lows where a bar exceeds N bars on
both sides, representing genuine market-structure reversal levels.
Exactly 2 entry conditions.

Entry (long):  close breaks ABOVE most recent pivot high
               AND bar range > 1.5 × ATR(14)
Entry (short): close breaks BELOW most recent pivot low
               AND bar range > 1.5 × ATR(14)
Exit (long):   close breaks BELOW most recent pivot low
               OR bar range < 1.0 × ATR(14)
Exit (short):  close breaks ABOVE most recent pivot high
               OR bar range < 1.0 × ATR(14)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, pivot_levels


class PivotBreakoutATR(Strategy):
    """Swing pivot breakout with ATR expansion confirmation.

    Uses pivot points — market-structure levels where price previously
    reversed — as breakout thresholds.  Unlike arbitrary N-bar channel
    breakouts, pivot levels are market-generated and self-updating.
    ATR expansion at 1.5× confirms genuine momentum behind the breakout.

    Parameters:
        pivot_bars: Left/right bars for pivot confirmation (default 5)
        atr_period: ATR smoothing lookback (default 14)
        expansion_mult: ATR expansion multiplier for entry (default 1.5)
    """

    timeframe = "1h"
    min_bars = 100  # enough for pivot formation + ATR warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "pivot_bars": 5,
        "atr_period": 14,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "PivotBreakoutATR"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from pivot breakout + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]    # type: ignore[assignment]
        low: pd.Series = df["low"]      # type: ignore[assignment]

        pivot_bars = self.params["pivot_bars"]
        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]

        # Compute indicators
        pivots = pivot_levels(df, left_bars=pivot_bars, right_bars=pivot_bars)
        pivot_high_level: pd.Series = pivots["pivot_high_level"]  # type: ignore[assignment]
        pivot_low_level: pd.Series = pivots["pivot_low_level"]    # type: ignore[assignment]
        atr_val = atr(df, period=atr_period)

        # Bar range
        bar_range = high - low

        # ATR expansion
        atr_expansion = bar_range > expansion_mult * atr_val
        atr_contraction = bar_range < 1.0 * atr_val

        # Pivot breakout detection (close breaks pivot level)
        # Use close at current bar vs pivot level
        pivot_high_break = close > pivot_high_level
        pivot_low_break = close < pivot_low_level

        # Previous bar was not broken (fresh breakout)
        prev_ph_break = pivot_high_break.shift(1).fillna(False)
        prev_pl_break = pivot_low_break.shift(1).fillna(False)

        fresh_high_break = pivot_high_break & ~prev_ph_break.astype(bool)
        fresh_low_break = pivot_low_break & ~prev_pl_break.astype(bool)

        # Entry (2 conditions: pivot breakout + ATR expansion)
        valid_atr = ~atr_val.isna()
        long_entry = fresh_high_break & atr_expansion & valid_atr
        short_entry = fresh_low_break & atr_expansion & valid_atr

        # Exit: reverse pivot break OR ATR contraction
        exit_long = pivot_low_break | atr_contraction
        exit_short = pivot_high_break | atr_contraction

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(atr_val.iloc[i]) or pd.isna(pivot_high_level.iloc[i]):
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
