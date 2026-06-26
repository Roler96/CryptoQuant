"""Chaikin Money Flow Trend Following strategy.

Trend-following strategy using Chaikin Money Flow (CMF) zero-cross
confirmed by an EMA200 trend filter.  Exactly 2 entry conditions.

Entry (long):  CMF crosses ABOVE 0 AND close > EMA200
Entry (short): CMF crosses BELOW 0 AND close < EMA200
Exit (long):   CMF crosses BELOW 0
Exit (short):  CMF crosses ABOVE 0

CMF accumulates the daily A/D formula over 21 periods: sum-based
(like CMO's successful pattern), not position-gating (unlike CLV).
The zero-cross threshold is fixed — no smoothed crossover that
compounds on 4h.

Reference: Marc Chaikin (1980s).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import cmf, ema


class CMFTrend(Strategy):
    """CMF zero-cross with EMA200 trend filter.

    Chaikin Money Flow measures the strength of accumulation/distribution
    by accumulating the A/D formula over a rolling window.  A zero-cross
    signals a shift in net money flow direction.  Entry requires both
    the zero-cross AND price trend alignment (close vs EMA200).

    Parameters:
        cmf_period: CMF accumulation period (default 21)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period + CMF warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "cmf_period": 21,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "CMFTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from CMF zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        cmf_period = self.params["cmf_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        cmf_val = cmf(df, period=cmf_period)
        ema_trend = ema(close, period=trend_period)

        # Zero-cross detection
        cmf_above_zero = cmf_val > 0
        cmf_below_zero = cmf_val < 0
        prev_above = cmf_above_zero.shift(1).fillna(False)
        prev_below = cmf_below_zero.shift(1).fillna(False)

        cross_up = cmf_above_zero & ~prev_above.astype(bool)
        cross_down = cmf_below_zero & ~prev_below.astype(bool)

        # Entry signals (2 conditions: CMF cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse CMF zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(cmf_val.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
