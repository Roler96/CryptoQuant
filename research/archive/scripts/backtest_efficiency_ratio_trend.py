"""Efficiency Ratio Trend Following strategy.

Trend-following strategy using Kaufman Efficiency Ratio (ER)
as a binary trend-quality signal, confirmed by EMA200 direction.
Exactly 2 entry conditions.

Entry (long):  ER > entry_threshold AND close > EMA200
Entry (short): ER > entry_threshold AND close < EMA200
Exit (long):   ER < exit_threshold (trend quality degrades)
Exit (short):  ER < exit_threshold

The Kaufman Efficiency Ratio directly measures how directional
price movement is — the ratio of net displacement to total path
length. ER ∈ [0, 1]: 0 = pure noise, 1 = pure trend. Unlike
all tested oscillators that measure momentum or smoothed rates,
ER measures the fundamental quality of the market.

Unlike KAMA (Loop 10, uses ER internally as smoothing coefficient),
this strategy uses ER directly as a binary signal — "is the market
trending efficiently?"

Reference: Perry Kaufman — "Trading Systems and Methods" (1998).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, efficiency_ratio


class EfficiencyRatioTrend(Strategy):
    """Efficiency Ratio threshold with EMA200 trend filter.

    ER measures directional price quality: values > entry_threshold
    indicate efficient trending (low noise path).  Entry requires
    ER > threshold plus EMA200 alignment.  Two conditions total.

    Parameters:
        er_period: ER computation lookback (default 20).
        entry_threshold: ER > this = trending, enter (default 0.4).
        exit_threshold: ER < this = noise, exit (default 0.2).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 220  # max(er_period, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "er_period": 20,
        "entry_threshold": 0.4,
        "exit_threshold": 0.2,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "EfficiencyRatioTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from ER threshold + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        er_period = self.params["er_period"]
        entry_threshold = self.params["entry_threshold"]
        exit_threshold = self.params["exit_threshold"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        er = efficiency_ratio(close, period=er_period)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: ER > threshold + EMA trend)
        er_high = er > entry_threshold
        er_low = er < exit_threshold

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = er_high & trend_up
        short_entry = er_high & trend_down

        # Exit: ER drops below exit threshold
        exit_long = er_low
        exit_short = er_low

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(er.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
