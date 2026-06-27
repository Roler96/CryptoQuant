"""Detrended Price Oscillator + ATR Expansion Breakout.

The Detrended Price Oscillator (DPO) removes the trend component from
price to isolate short-term cycles.  DPO zero-cross signals indicate
the cycle has turned — either from trough to peak (crossover above
zero) or from peak to trough (crossunder below zero).

Combined with ATR expansion confirmation (the universal filter proven
effective across multiple research loops), this creates a cycle +
volatility breakout hybrid with exactly 2 entry conditions.

Entry (long):  DPO crosses ABOVE zero AND ATR expanding
Entry (short): DPO crosses BELOW zero AND ATR expanding
Exit (long):   DPO crosses BELOW zero
Exit (short):  DPO crosses ABOVE zero

DPO = Close — SMA(Close, N/2+1), displaced forward by N/2+1 bars.
The displacement centers the SMA, making the oscillator oscillate
around zero — cycles are visible as zero-crosses.

Reference: William Blau — "Momentum, Direction, and Divergence" (1995).
The DPO was popularized by John Ehlers for cycle analysis.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, sma


class DPOTrend(Strategy):
    """DPO zero-cross with ATR expansion confirmation.

    Entry: DPO zero-cross (cycle turn) + ATR expansion (volatility confirmation).
    Exit:  reverse DPO zero-cross.

    Parameters:
        dpo_period: DPO lookback period (default 20)
        atr_period: ATR period for expansion check (default 14)
        expansion_mult: Expansion multiplier threshold (default 1.5)
    """

    timeframe = "1h"
    min_bars = 200  # warmup: 20 (DPO sma) + 14 (ATR) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "dpo_period": 20,
        "atr_period": 14,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "DPOTrend"

    def _compute_dpo(self, close: pd.Series, period: int) -> pd.Series:
        """Compute Detrended Price Oscillator.

        DPO = Close — SMA(Close, N/2+1), displaced forward N/2+1 bars.
        The displacement removes the trend and centers the oscillator at zero.
        """
        n = period
        half = n // 2 + 1
        sma_centered = sma(close, period=half)
        # Displace SMA forward by N/2+1 bars to center it
        sma_displaced = sma_centered.shift(-half)
        dpo = close - sma_displaced
        return dpo

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from DPO zero-crosses + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        bar_range: pd.Series = df["high"] - df["low"]  # type: ignore[assignment]

        dpo_period = self.params["dpo_period"]
        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]

        # Compute DPO
        dpo = self._compute_dpo(close, period=dpo_period)

        # Compute ATR expansion check
        atr_val = atr(df, period=atr_period)
        atr_expanding = bar_range > (expansion_mult * atr_val)

        # DPO zero-cross detection
        dpo_above = dpo > 0
        dpo_below = dpo < 0
        prev_above = dpo_above.shift(1).fillna(False)
        prev_below = dpo_below.shift(1).fillna(False)

        cross_up = dpo_above & ~prev_above.astype(bool)
        cross_down = dpo_below & ~prev_below.astype(bool)

        # Entry signals (2 conditions: DPO cross + ATR expansion)
        long_entry = cross_up & atr_expanding
        short_entry = cross_down & atr_expanding

        # Exit signals: reverse DPO zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(dpo.iloc[i]) or pd.isna(atr_expanding.iloc[i]):
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
