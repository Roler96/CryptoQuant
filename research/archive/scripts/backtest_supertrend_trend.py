"""SuperTrend Trend Following strategy.

Acceleration-based trend-following strategy using SuperTrend confirmed
by an EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  close > SuperTrend AND close > EMA200
Entry (short): close < SuperTrend AND close < EMA200
Exit (long):   close < SuperTrend (SuperTrend flips bearish)
Exit (short):  close > SuperTrend (SuperTrend flips bullish)

SuperTrend is an ATR-based trailing stop — similar to PSAR but uses
volatility-based band distance instead of an acceleration factor.
This makes it potentially more adaptive to crypto's variable volatility.

Reference: Olivier Seban (2008) — SuperTrend indicator; Boring Edge
SuperTrend backtest 2017-2026.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, supertrend


class SuperTrendTrend(Strategy):
    """SuperTrend with EMA200 trend filter.

    Entry requires both SuperTrend direction alignment and EMA200
    trend confirmation. Exit on SuperTrend reversal.

    Parameters:
        atr_period: ATR period for SuperTrend (default 10)
        multiplier: ATR multiplier for band width (default 2.5)
        trend_period: EMA period for trend filter (default 200)
    """

    timeframe = "1h"
    min_bars = 300  # trend_period + supertrend warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "atr_period": 10,
        "multiplier": 2.5,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "SuperTrendTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from SuperTrend flips + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        atr_period = self.params["atr_period"]
        multiplier = self.params["multiplier"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        st_vals = supertrend(df, atr_period=atr_period, multiplier=multiplier)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: SuperTrend position + EMA trend)
        above_st = close > st_vals
        below_st = close < st_vals

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = above_st & trend_up
        short_entry = below_st & trend_down

        # Exit signals: price crosses SuperTrend
        exit_long = below_st
        exit_short = above_st

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(st_vals.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
