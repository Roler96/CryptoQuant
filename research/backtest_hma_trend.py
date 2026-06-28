"""HMA Trend — Hull Moving Average Crossover + Trend Filter.

Trend-following strategy using HMA fast/slow crossover confirmed by
EMA200 trend direction. Exactly 2 entry conditions.

The HMA (Hull Moving Average, 2005) uses WMA triple-weighting to
achieve near-zero lag while maintaining smoothness. Similar to ALMA's
Gaussian offset but achieved through WMA subtraction rather than
Gaussian kernel — mathematically distinct mechanism.

Entry (long):  HMA(fast) > HMA(slow) AND close > EMA200
Entry (short): HMA(fast) < HMA(slow) AND close < EMA200
Exit (long):   HMA(fast) < HMA(slow) (reverse crossover)
Exit (short):  HMA(fast) > HMA(slow) (reverse crossover)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, hma


class HMATrend(Strategy):
    """Hull Moving Average crossover with EMA200 trend filter.

    HMA uses a WMA triple-weighting scheme (2 × WMA(n/2) − WMA(n)
    smoothed by WMA(√n)) to reduce lag dramatically compared to
    standard EMAs. This preserves signal density — especially on
    4h where crossover frequency is critical.

    Parameters:
        hma_fast: Fast HMA period (default 9).
        hma_slow: Slow HMA period (default 21).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 235  # max(hma_slow, trend_period) + 35
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "hma_fast": 9,
        "hma_slow": 21,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "HMATrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from HMA crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        hma_fast = self.params["hma_fast"]
        hma_slow = self.params["hma_slow"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        fast_hma = hma(close, period=hma_fast)
        slow_hma = hma(close, period=hma_slow)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: HMA crossover + trend filter)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        hma_cross_up = fast_hma > slow_hma
        hma_cross_down = fast_hma < slow_hma

        long_entry = trend_up & hma_cross_up
        short_entry = trend_down & hma_cross_down

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
                or pd.isna(ema_trend.iloc[i])
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
