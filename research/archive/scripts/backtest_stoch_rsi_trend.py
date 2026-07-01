"""Stochastic RSI Trend strategy.

Trend-following momentum strategy using Stochastic %K/%D crossover
confirmed by a long-term EMA trend filter. Exactly 2 entry conditions.

Entry (long):  Stoch %K crosses ABOVE %D AND close > EMA(trend_period)
Entry (short): Stoch %K crosses BELOW %D AND close < EMA(trend_period)
Exit:          Reverse crossover of Stoch %K/%D (momentum exhausted)

Reference: ChartSchool — Stochastic Oscillator; Investopedia — Combining
Stochastic with Moving Averages. arXiv:2510.08068 validates multi-indicator
combinations on Bitcoin.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import crossover, crossunder, ema, stochastic


class StochRSITrend(Strategy):
    """Stochastic Momentum with EMA Trend Filter.

    Uses Stoch %K/%D crossover for momentum entry, gated by a long-term
    EMA trend filter to avoid counter-trend entries. Exit on reverse
    crossover regardless of trend filter.

    Parameters:
        k_period: Stochastic %K lookback (default 14)
        d_period: Stochastic %D smoothing (default 3)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 250  # trend_period + k_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "k_period": 14,
        "d_period": 3,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "StochRSITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Stochastic crossover + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        k_period = self.params["k_period"]
        d_period = self.params["d_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        stoch = stochastic(df, k_period=k_period, d_period=d_period)
        stoch_k: pd.Series = stoch["k"]  # type: ignore[assignment]
        stoch_d: pd.Series = stoch["d"]  # type: ignore[assignment]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: momentum cross + trend direction)
        long_cross = crossover(stoch_k, stoch_d).astype(bool)
        short_cross = crossunder(stoch_k, stoch_d).astype(bool)

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = long_cross & trend_up
        short_entry = short_cross & trend_down

        # Exit signals: reverse crossover (momentum exhausted)
        exit_long = short_cross
        exit_short = long_cross

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(stoch_k.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
