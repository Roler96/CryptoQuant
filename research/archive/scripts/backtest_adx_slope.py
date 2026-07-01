"""ADX Slope Trend Following strategy.

Trend-following strategy using ADX slope (change in trend strength)
as the entry trigger, confirmed by an EMA200 trend filter.
Exactly 2 entry conditions.

Entry (long):  ADX slope > 0 AND close > EMA200
Entry (short): ADX slope < 0 AND close < EMA200
Exit (long):   ADX slope reverses direction (slope < 0)
Exit (short):  ADX slope reverses direction (slope > 0)

Unlike ADX threshold strategies (ADX > 25) which detect trend
EXISTENCE late, ADX slope detects trend INTENSIFICATION early.
ADX increasing means trend strength is building; ADX decreasing
means trend strength is waning.

Reference: J. Welles Wilder — "New Concepts in Technical Trading
Systems" (1978), adapted with slope-based entry.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import adx, ema


class ADXSlopeTrend(Strategy):
    """ADX slope zero-cross with EMA200 trend filter.

    Uses rate-of-change of ADX (not absolute ADX level) to enter
    trades when trend strength is INTENSIFYING, not merely present.
    This solves the ADX>25 latency problem on 4h timeframes where
    ADX takes 56+ hours to cross the standard threshold.

    Parameters:
        adx_period: ADX lookback period (default 14)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period + ADX warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "adx_period": 14,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ADXSlopeTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from ADX slope zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        adx_period = self.params["adx_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        adx_df = adx(df, period=adx_period)
        adx_val = adx_df["adx"]
        adx_slope = adx_val.diff()  # ADX[t] - ADX[t-1]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: ADX slope + EMA trend)
        slope_up = adx_slope > 0
        slope_down = adx_slope < 0
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = slope_up & trend_up
        short_entry = slope_down & trend_down

        # Exit signals: ADX slope reverses direction
        exit_long = slope_down
        exit_short = slope_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(adx_slope.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
