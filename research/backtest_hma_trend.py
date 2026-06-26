"""Hull Moving Average Trend Following strategy.

Trend-following strategy using HMA crossover confirmed by ATR
expansion. Exactly 2 entry conditions, following the proven
2-condition template across 12+ loops of research.

Entry (long):  fast_hma > slow_hma AND bar_range > 1.5× ATR(14)
Entry (short): fast_hma < slow_hma AND bar_range > 1.5× ATR(14)
Exit (long):   fast_hma < slow_hma (reverse crossover)
Exit (short):  fast_hma > slow_hma (reverse crossover)

HMA (Hull Moving Average, 2005) achieves near-zero lag vs traditional
EMAs. Paired with ATR expansion (the strongest single confirmation
filter across Loops 5-6, 11), this should produce 50-200 trades/year.

Reference: Alan Hull — "The Hull Moving Average" (2005).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, hma


class HMATrend(Strategy):
    """Hull Moving Average crossover with ATR expansion filter.

    HMA crossover provides the trend direction signal with minimal
    lag.  ATR expansion confirms genuine trend initiation rather than
    noise.  Two conditions total, matching the proven template.

    Parameters:
        hma_fast: Fast HMA period (default 20).
        hma_slow: Slow HMA period (default 50).
        atr_period: ATR period (default 14).
        expansion_mult: ATR expansion multiplier (default 1.5).
    """

    timeframe = "1h"
    min_bars = 55  # max(hma_slow, atr_period) + 5
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "hma_fast": 20,
        "hma_slow": 50,
        "atr_period": 14,
        "expansion_mult": 1.5,
    }

    @property
    def name(self) -> str:
        return "HMATrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from HMA crossover + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]    # type: ignore[assignment]
        low: pd.Series = df["low"]      # type: ignore[assignment]

        hma_fast = self.params["hma_fast"]
        hma_slow = self.params["hma_slow"]
        atr_period = self.params["atr_period"]
        expansion_mult = self.params["expansion_mult"]

        # Compute indicators
        fast_hma = hma(close, period=hma_fast)
        slow_hma = hma(close, period=hma_slow)
        atr_val = atr(df, period=atr_period)
        bar_range = high - low

        # Entry signals (2 conditions: HMA crossover + ATR expansion)
        trend_up = close > slow_hma
        trend_down = close < slow_hma

        hma_cross_up = fast_hma > slow_hma
        hma_cross_down = fast_hma < slow_hma

        atr_expansion = bar_range > (expansion_mult * atr_val)

        long_entry = trend_up & hma_cross_up & atr_expansion
        short_entry = trend_down & hma_cross_down & atr_expansion

        # Exit: HMA reverse crossover
        exit_long = hma_cross_down
        exit_short = hma_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(fast_hma.iloc[i])
                or pd.isna(slow_hma.iloc[i])
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
