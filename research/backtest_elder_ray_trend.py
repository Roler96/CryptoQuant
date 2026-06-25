"""Elder Ray Trend strategy.

Uses Elder's Bull/Bear Power (price extremes vs EMA) as a fast
oscillator with a long-term trend filter. Exactly 2 entry conditions.

Entry (long):  Bull Power > 0 AND Close > EMA(200)
Entry (short): Bear Power < 0 AND Close < EMA(200)
Exit (long):   Bull Power <= 0 (buying pressure exhausted)
Exit (short):  Bear Power >= 0 (selling pressure exhausted)

Elder Ray measures raw buying/selling pressure without smoothing or
normalization, making it faster than RSI, Stochastic, or MACD. The
EMA200 trend filter adds directional bias. 2 conditions only —
no AND-gates, no regime switching, no hysteresis.

Reference: Alexander Elder — "Trading for a Living" (1993).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class ElderRayTrend(Strategy):
    """Elder Ray Bull/Bear Power with trend filter.

    Entry requires Bull/Bear Power zero-cross AND EMA200 alignment.

    Parameters:
        ema_period: Period for Bull/Bear Power EMA (default 13)
        trend_period: Period for trend filter EMA (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ema_period": 13,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ElderRayTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Elder Ray power + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]   # type: ignore[assignment]
        low: pd.Series = df["low"]     # type: ignore[assignment]

        ema_period = self.params["ema_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        ema_short = ema(close, period=ema_period)

        # Elder Ray: Bull Power = high - EMA, Bear Power = low - EMA
        bull_power = high - ema_short
        bear_power = low - ema_short

        # Entry signals: 2 conditions (power zero-cross + trend filter)
        long_entry = (bull_power > 0) & (close > ema_trend)
        short_entry = (bear_power < 0) & (close < ema_trend)

        # Exit signals: power crosses back
        exit_long = bull_power <= 0
        exit_short = bear_power >= 0

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(bull_power.iloc[i]):
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
