"""MAMA/FAMA Adaptive Trend strategy.

Trend-following strategy using MAMA (MESA Adaptive Moving Average)
crossover with FAMA (Following Adaptive Moving Average), confirmed by
EMA200 trend direction filter.  Exactly 2 entry conditions.

MAMA adapts its EMA alpha based on the Hilbert Transform's measured
rate of phase change — fast attack at cycle turning points, slow decay
during trend continuation.  This creates a ratcheting moving average
that is "virtually free of whipsaw" (Ehlers).

Entry (long):  MAMA crosses above FAMA AND close > EMA200
Entry (short): MAMA crosses below FAMA AND close < EMA200
Exit:          MAMA crosses back below/above FAMA (reverse signal)

Reference: John Ehlers — "MAMA – The Mother of Adaptive Moving
Averages" (MESA Software).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, mama_fama, crossover, crossunder


class MamaFamaTrend(Strategy):
    """MAMA/FAMA adaptive crossover with EMA200 trend filter.

    Uses Hilbert Transform to measure cycle phase change, then adapts
    MAMA's alpha accordingly.  MAMA/FAMA crossover is the primary
    trigger; EMA200 provides directional confirmation.  2 conditions.

    Parameters:
        fast_limit: Maximum MAMA alpha (default 0.5).
        slow_limit: Minimum MAMA alpha (default 0.05).
        trend_period: EMA period for trend direction filter (default 200).
    """

    timeframe = "1h"
    min_bars = 220  # trend_period + Hilbert warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "fast_limit": 0.5,
        "slow_limit": 0.05,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "MamaFamaTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from MAMA/FAMA crossover + EMA200 direction.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        fast_limit = self.params["fast_limit"]
        slow_limit = self.params["slow_limit"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        mf = mama_fama(df, fast_limit=fast_limit, slow_limit=slow_limit)
        mama_line: pd.Series = mf["mama"]  # type: ignore[assignment]
        fama_line: pd.Series = mf["fama"]  # type: ignore[assignment]
        trend_line = ema(close, period=trend_period)

        # Entry signals (2 conditions: MAMA/FAMA cross + trend direction)
        long_entry = (
            crossover(mama_line, fama_line).astype(bool)
            & (close > trend_line)
        )
        short_entry = (
            crossunder(mama_line, fama_line).astype(bool)
            & (close < trend_line)
        )

        # Exit signals: reverse crossover
        exit_long = crossunder(mama_line, fama_line).astype(bool)
        exit_short = crossover(mama_line, fama_line).astype(bool)

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(mama_line.iloc[i])
                or pd.isna(fama_line.iloc[i])
                or pd.isna(trend_line.iloc[i])
            ):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip to short
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip to long
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
