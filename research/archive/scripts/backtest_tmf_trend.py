"""TMF Trend Following strategy.

Trend-following strategy using Twiggs Money Flow (TMF) zero-cross
+ EMA200 trend filter. Exactly 2 entry conditions.

TMF is a volume-weighted money flow indicator that improves on CMF
by using True Range normalization (instead of High-Low range) and
Wilder EMA smoothing (instead of simple sum).

Entry (long):  TMF crosses above 0 AND close > EMA200
Entry (short): TMF crosses below 0 AND close < EMA200
Exit (long):   TMF crosses below 0 (money flow reversal)
Exit (short):  TMF crosses above 0

Reference: Colin Twiggs — "Twiggs Money Flow" (Incredible Charts).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, twiggs_money_flow


class TMFTrend(Strategy):
    """Twiggs Money Flow zero-cross with EMA200 trend filter.

    TMF measures accumulation/distribution via volume-weighted money flow
    with True Range normalization. Entry requires TMF crossing zero AND
    price trend alignment (EMA200).

    Parameters:
        tmf_period: TMF Wilder EMA smoothing period (default 21)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period(200) + warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "tmf_period": 21,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "TMFTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TMF zero-cross + EMA200 trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        tmf_period = self.params["tmf_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        tmf_val = twiggs_money_flow(df, period=tmf_period)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: TMF zero-cross + EMA200 trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        # Two-bar cross detection: TMF crosses above/below zero
        tmf_prev = tmf_val.shift(1)
        tmf_cross_above = (tmf_val > 0) & (tmf_prev <= 0)
        tmf_cross_below = (tmf_val < 0) & (tmf_prev >= 0)

        long_entry = tmf_cross_above & trend_up
        short_entry = tmf_cross_below & trend_down

        # Exit signals: TMF crosses back through zero
        exit_long = tmf_cross_below
        exit_short = tmf_cross_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(tmf_val.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
