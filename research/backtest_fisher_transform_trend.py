"""Fisher Transform Trend Following strategy.

Trend-following strategy using Fisher Transform crossover
confirmed by EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  Fisher > signal line AND close > EMA200
Entry (short): Fisher < signal line AND close < EMA200
Exit (long):   Fisher crosses below signal line
Exit (short):  Fisher crosses above signal line

The Fisher Transform (Ehlers, 2002) converts any price waveform
into a Gaussian normal distribution, producing sharp peaks at
turning points. Unlike smoothed oscillators (RSI, Stochastic),
Fisher signals are binary on/off rather than gradual threshold
crossings — making entry timing more precise.

Reference: John Ehlers — "Using the Fisher Transform"
(Stocks & Commodities, Nov 2002).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, fisher_transform


class FisherTransformTrend(Strategy):
    """Fisher Transform crossover with EMA200 trend filter.

    Fisher Transform converts median price into a Gaussian
    distribution where peaks correspond to turning points.
    Entry requires Fisher > signal line (momentum) plus
    EMA200 alignment (trend direction).  Two conditions total.

    Parameters:
        fisher_period: Normalization lookback (default 10).
        signal_period: Signal line EMA smoothing (default 5).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(fisher_period, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "fisher_period": 10,
        "signal_period": 5,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "FisherTransformTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Fisher Transform crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        fisher_period = self.params["fisher_period"]
        signal_period = self.params["signal_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ft = fisher_transform(df, fisher_period=fisher_period, signal_period=signal_period)
        fisher = ft["fisher"]
        signal_line = ft["signal"]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: Fisher crossover + EMA trend)
        fisher_above = fisher > signal_line
        fisher_below = fisher < signal_line

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = fisher_above & trend_up
        short_entry = fisher_below & trend_down

        # Exit: Fisher crosses below/above signal line
        exit_long = fisher_below
        exit_short = fisher_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(fisher.iloc[i]) or pd.isna(signal_line.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
