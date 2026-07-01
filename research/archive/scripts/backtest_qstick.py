"""Qstick Trend Following strategy.

Trend-following strategy using Qstick (SMA of close-open difference)
zero-cross confirmed by an EMA200 trend filter.
Exactly 2 entry conditions.

Entry (long):  Qstick crosses ABOVE zero AND close > EMA200
Entry (short): Qstick crosses BELOW zero AND close < EMA200
Exit (long):   Qstick crosses BELOW zero
Exit (short):  Qstick crosses ABOVE zero

Qstick = SMA(close - open, N) measures the running average of
per-bar directional conviction. Unlike momentum oscillators that
compare close[t] vs close[t-N], Qstick captures whether buyers
or sellers are winning bar-by-bar.

Reference: Tushar Chande — "Beyond Technical Analysis" (1997).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, qstick


class QstickTrend(Strategy):
    """Qstick zero-cross with EMA200 trend filter.

    Qstick measures the running average of per-bar directional bias.
    A zero-cross signals a shift from average selling pressure to
    average buying pressure (or vice versa). Entry requires both
    the zero-cross AND price trend alignment (close vs EMA200).

    Unlike CandleConvictionBreakout (which used a strict body_ratio > 0.6
    boolean gate and produced 1-6 trades/year), Qstick preserves the raw
    magnitude of close-open as a weighted signal, maintaining trade count.

    Parameters:
        qstick_period: Qstick SMA period (default 14)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period + Qstick warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "qstick_period": 14,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "QstickTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Qstick zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        qstick_period = self.params["qstick_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        qs = qstick(df, period=qstick_period)
        ema_trend = ema(close, period=trend_period)

        # Zero-cross detection
        qs_above_zero = qs > 0
        qs_below_zero = qs < 0
        prev_above = qs_above_zero.shift(1).fillna(False)
        prev_below = qs_below_zero.shift(1).fillna(False)

        cross_up = qs_above_zero & ~prev_above.astype(bool)
        cross_down = qs_below_zero & ~prev_below.astype(bool)

        # Entry signals (2 conditions: Qstick cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse Qstick zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(qs.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
