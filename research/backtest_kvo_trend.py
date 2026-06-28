"""KVO Trend Following strategy.

Trend-following strategy using Klinger Volume Oscillator (KVO)
zero-line crossover confirmed by EMA200 trend filter.  Exactly
2 entry conditions.

KVO uses Volume Force — a volume-directional measure that weights
volume by intra-bar range and trend direction.  Unlike OBV (binary
accumulation) and PVT (proportional accumulation), KVO uses a
dual-EMA structure (34/55) on Volume Force to produce an oscillator
that identifies volume-flow direction changes.

Entry (long):  KVO crosses above zero AND close > EMA200
Entry (short): KVO crosses below zero AND close < EMA200
Exit (long):   KVO crosses below zero
Exit (short):  KVO crosses above zero

Reference: Stephen Klinger — "Klinger Volume Oscillator" (1997).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, kvo


class KVOTrend(Strategy):
    """KVO zero-line crossover with EMA200 trend filter.

    Entry requires KVO crossover AND EMA200 alignment.
    Two conditions total.

    Parameters:
        kvo_fast: Fast EMA period for KVO (default 34).
        kvo_slow: Slow EMA period for KVO (default 55).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(kvo_slow=55, trend_period=200) + 10
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "kvo_fast": 34,
        "kvo_slow": 55,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "KVOTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from KVO zero-line crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        kvo_fast = self.params["kvo_fast"]
        kvo_slow = self.params["kvo_slow"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        kvo_df = kvo(df, fast=kvo_fast, slow=kvo_slow)
        kvo_val = kvo_df["kvo"]
        zero_line = kvo_df["zero"]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: KVO crossover + EMA trend)
        kvo_above = kvo_val > zero_line
        kvo_below = kvo_val < zero_line

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = kvo_above & trend_up
        short_entry = kvo_below & trend_down

        # Exit: KVO crosses back
        exit_long = kvo_below
        exit_short = kvo_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(kvo_val.iloc[i])
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
