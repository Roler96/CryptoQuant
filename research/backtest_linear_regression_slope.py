"""Linear Regression Slope Trend — pure slope-direction strategy.

Uses linear regression slope crossing a threshold as the primary entry
trigger, confirmed by EMA trend direction. Exactly 2 entry conditions.

Unlike existing LinRegTrend (which gates entry on R² > 0.7, adding a
de-facto 3rd condition), this strategy uses only slope magnitude —
giving it simpler semantics and likely higher signal density.

Entry (long):  slope > slope_threshold AND close > EMA(trend_period)
Entry (short): slope < -slope_threshold AND close < EMA(trend_period)
Exit (long):   slope crosses below 0 (reverse)
Exit (short):  slope crosses above 0 (reverse)

Reference: Standard statistical method (OLS slope of close vs bar index).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, linreg


class LinearRegressionSlope(Strategy):
    """Linear regression slope trend with EMA trend filter.

    Entry requires slope above threshold AND EMA directional alignment.
    Exit when slope crosses zero (momentum reverses).

    Parameters:
        lr_period: Rolling window for linear regression (default 20).
        slope_threshold: Minimum absolute slope to enter (default 0.0).
        trend_period: Period for trend filter EMA (default 200).
    """

    timeframe = "1h"
    min_bars = 220  # lr_period + trend_period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lr_period": 20,
        "slope_threshold": 0.0,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "LinearRegressionSlope"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from LR slope + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        lr_period = self.params["lr_period"]
        slope_threshold = self.params["slope_threshold"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        lr = linreg(close, period=lr_period)
        slope = lr["slope"]

        # Entry signals: 2 conditions (slope threshold + trend filter)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = (slope > slope_threshold) & trend_up
        short_entry = (slope < -slope_threshold) & trend_down

        # Exit: slope crosses zero
        exit_long = slope < 0
        exit_short = slope > 0

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(slope.iloc[i]):
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
