"""Linear Regression Trend strategy.

Uses rolling linear regression R² (trend quality) and slope (direction)
confirmed by EMA100 trend filter. Exactly 2 entry conditions.

Entry (long):  R² > r2_entry AND Close > EMA(trend_period)
Entry (short): R² > r2_entry AND Close < EMA(trend_period)
Exit:          R² drops below r2_exit (trend weakens)

R² measures how well price fits a linear trend — high R² means price
is moving directionally rather than randomly. This directly measures
trend "quality" without the lag of smoothed indicators.

Reference: Standard statistical method (OLS linear regression).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, linreg


class LinRegTrend(Strategy):
    """Linear regression R² trend quality with EMA trend filter.

    Entry requires R² above entry threshold AND EMA directional alignment.
    Exit when R² drops below exit threshold.

    Parameters:
        linreg_period: Rolling window for linear regression (default 30)
        r2_entry: Minimum R² to enter a trade (default 0.7)
        r2_exit: R² threshold for exit (default 0.3)
        trend_period: Period for trend filter EMA (default 100)
    """

    timeframe = "1h"
    min_bars = 130  # linreg_period + trend_period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "linreg_period": 30,
        "r2_entry": 0.7,
        "r2_exit": 0.3,
        "trend_period": 100,
    }

    @property
    def name(self) -> str:
        return "LinRegTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from R² trend quality + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        linreg_period = self.params["linreg_period"]
        r2_entry = self.params["r2_entry"]
        r2_exit = self.params["r2_exit"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        lr = linreg(close, period=linreg_period)
        r2 = lr["r2"]
        slope = lr["slope"]

        # Entry signals: 2 conditions (R² quality + trend filter)
        long_entry = (r2 > r2_entry) & (close > ema_trend) & (slope > 0)
        short_entry = (r2 > r2_entry) & (close < ema_trend) & (slope < 0)

        # Exit: R² weakens
        exit_long = r2 <= r2_exit
        exit_short = r2 <= r2_exit

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(r2.iloc[i]):
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
