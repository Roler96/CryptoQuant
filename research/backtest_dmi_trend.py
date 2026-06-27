"""DMI Trend strategy.

Uses Directional Movement Index (DMI) crossover confirmed by EMA200
trend filter. Exactly 2 entry conditions.

Entry (long):  +DI(14) > -DI(14) AND Close > EMA(200)
Entry (short): -DI(14) > +DI(14) AND Close < EMA(200)
Exit:          Reverse DMI crossover

+DI and -DI measure raw directional movement normalized by True Range
(a component of the ADX system, from the existing adx() function).
Unlike ADX (which smooths the absolute difference between +DI and -DI),
the raw crossover fires on genuine directional shifts without the
additional smoothing layer that causes 4h trade scarcity.

Inspired by VortexTrend (Loop 17, 3/4 pass) — DMI uses Wilder-smoothed
+DM/-DM while Vortex uses rolling sums, but both compare directional
movement components directly.

Reference: J. Welles Wilder — "New Concepts in Technical Trading Systems" (1978).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import adx, ema


class DMITrend(Strategy):
    """DMI crossover with EMA200 trend filter.

    Entry requires +DI crosses above -DI (long) or -DI crosses above +DI
    (short) AND EMA200 directional alignment.

    Parameters:
        di_period: DMI lookback period (default 14, Wilder standard)
        trend_period: Period for trend filter EMA (default 200)
    """

    timeframe = "1h"
    min_bars = 215  # trend_period + di_period + margin
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "di_period": 14,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "DMITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from DMI crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        di_period = self.params["di_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        adx_df = adx(df, period=di_period)
        pdi = adx_df["pdi"]
        mdi = adx_df["mdi"]

        # Entry signals: 2 conditions (DMI crossover + trend filter)
        long_entry = (pdi > mdi) & (close > ema_trend)
        short_entry = (mdi > pdi) & (close < ema_trend)

        # Exit: reverse crossover
        exit_long = pdi <= mdi
        exit_short = mdi <= pdi

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(pdi.iloc[i]):
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
