"""ALMA Trend — Arnaud Legoux Moving Average Crossover + Trend Filter.

Trend-following strategy using ALMA fast/slow crossover confirmed by
EMA200 trend direction. Exactly 2 entry conditions, following the
proven 2-condition template.

The ALMA (Arnaud Legoux Moving Average, 2009) uses Gaussian weighting
with adjustable offset to achieve near-zero lag while maintaining
smoothness. Unlike EMAs (lag ~period/2) or HMAs (WMA-based with sqrt
lookback), ALMA applies a Gaussian kernel — this is the first time
this MA type has been tested in this research pipeline.

Entry (long):  ALMA(fast) > ALMA(slow) AND close > EMA200
Entry (short): ALMA(fast) < ALMA(slow) AND close < EMA200
Exit (long):   ALMA(fast) < ALMA(slow) (reverse crossover)
Exit (short):  ALMA(fast) > ALMA(slow) (reverse crossover)
Stop-loss:     2× ATR(14) (handled by engine)
Take-profit:   3× ATR(14) (handled by engine)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import alma, ema


class ALMATrend(Strategy):
    """Arnaud Legoux Moving Average crossover with EMA200 trend filter.

    ALMA uses a Gaussian weighting function with adjustable offset to
    produce a moving average with near-zero lag. The fast/slow crossover
    provides the trend direction signal, and EMA200 confirms macro trend.

    Parameters:
        alma_fast: Fast ALMA period (default 9).
        alma_slow: Slow ALMA period (default 30).
        alma_offset: Gaussian center offset (default 0.85).
        alma_sigma: Gaussian width parameter (default 6.0).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 235  # max(alma_slow, trend_period) + 35
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "alma_fast": 9,
        "alma_slow": 30,
        "alma_offset": 0.85,
        "alma_sigma": 6.0,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ALMATrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from ALMA crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        alma_fast = self.params["alma_fast"]
        alma_slow = self.params["alma_slow"]
        alma_offset = self.params["alma_offset"]
        alma_sigma = self.params["alma_sigma"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        fast_alma = alma(close, period=alma_fast, offset=alma_offset,
                         sigma=alma_sigma)
        slow_alma = alma(close, period=alma_slow, offset=alma_offset,
                         sigma=alma_sigma)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: ALMA crossover + trend filter)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        alma_cross_up = fast_alma > slow_alma
        alma_cross_down = fast_alma < slow_alma

        long_entry = trend_up & alma_cross_up
        short_entry = trend_down & alma_cross_down

        # Exit: ALMA reverse crossover
        exit_long = alma_cross_down
        exit_short = alma_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(fast_alma.iloc[i])
                or pd.isna(slow_alma.iloc[i])
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
