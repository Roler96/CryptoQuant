"""Aroon Trend Continuation strategy.

Trend-following strategy using Aroon directional readings confirmed by
a medium-term EMA trend filter. Exactly 2 entry conditions.

Entry (long):  Aroon Up > 70 AND close > EMA(trend_period)
Entry (short): Aroon Down > 70 AND close < EMA(trend_period)
Exit (long):   Aroon Up < 50 (trend weakening)
Exit (short):  Aroon Down < 50 (trend weakening)

Unlike ADX (which measures smoothed trend strength), Aroon directly
measures recency of highs/lows — producing faster, more responsive
signals that should work on both 1h and 4h timeframes.

Reference: ChartSchool — Aroon Indicator; Investopedia — Aroon: Early
Trend Detection. arXiv:2510.07943 validates multi-indicator combinations.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import aroon, ema


class AroonTrendContinuation(Strategy):
    """Aroon Trend Continuation with EMA Trend Filter.

    Uses Aroon directional readings (> threshold) for trend continuation
    entry, confirmed by EMA trend filter. Exit when Aroon weakens
    (drops below exit threshold).

    Parameters:
        aroon_period: Aroon lookback period (default 25)
        aroon_threshold: Entry threshold for Aroon reading (default 70)
        aroon_exit: Exit threshold — Aroon below this exits (default 50)
        trend_period: EMA trend filter lookback (default 50)
    """

    timeframe = "1h"
    min_bars = 80  # aroon_period + trend_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "aroon_period": 25,
        "aroon_threshold": 70,
        "aroon_exit": 50,
        "trend_period": 50,
    }

    @property
    def name(self) -> str:
        return "AroonTrendContinuation"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Aroon trend readings + EMA filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        aroon_period = self.params["aroon_period"]
        aroon_threshold = self.params["aroon_threshold"]
        aroon_exit = self.params["aroon_exit"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        aroon_df = aroon(df, period=aroon_period)
        aroon_up = aroon_df["aroon_up"]
        aroon_down = aroon_df["aroon_down"]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: Aroon direction + EMA trend)
        aroon_long = aroon_up > aroon_threshold
        aroon_short = aroon_down > aroon_threshold

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = aroon_long & trend_up
        short_entry = aroon_short & trend_down

        # Exit signals: Aroon weakens
        exit_long = aroon_up < aroon_exit
        exit_short = aroon_down < aroon_exit

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(aroon_up.iloc[i]) or pd.isna(ema_trend.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
