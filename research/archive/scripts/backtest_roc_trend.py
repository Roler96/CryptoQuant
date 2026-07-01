"""ROC Trend Following strategy.

Trend-following strategy using raw Rate of Change (ROC) zero-line
crossover as the primary entry trigger, confirmed by EMA200 trend
filter.  Exactly 2 entry conditions — matches the proven 2-condition
template.

ROC(20) is the simplest possible momentum measure: the percentage
price change over the last 20 bars with zero normalization. Unlike
CMO, RiskAdjustedMomentum, or Z-score momentum (which all apply
normalization before thresholding), ROC tests whether raw price
change contains enough signal to profit in crypto markets.

Entry (long):  ROC(20) crosses above 0 AND close > EMA(200)
Entry (short): ROC(20) crosses below 0 AND close < EMA(200)
Exit (long):   ROC crosses below 0 (reverse signal)
Exit (short):  ROC crosses above 0 (reverse signal)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, roc


class ROCTrend(Strategy):
    """ROC zero-line crossover with EMA200 trend filter.

    Parameters:
        roc_period: ROC lookback period (default 20).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 100  # max(roc_period=20, trend_period=200) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "roc_period": 20,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ROCTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from ROC zero-cross + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        roc_period = self.params["roc_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        roc_val = roc(close, period=roc_period)
        ema_trend = ema(close, period=trend_period)

        # Entry conditions (2 conditions: ROC zero-cross + EMA trend)
        roc_above = roc_val > 0
        roc_below = roc_val < 0

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = roc_above & trend_up
        short_entry = roc_below & trend_down

        # Exit: ROC crosses back across zero
        exit_long = roc_below
        exit_short = roc_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(roc_val.iloc[i])
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
