"""Ultimate Oscillator Trend Following strategy.

Trend-following strategy using Ultimate Oscillator (UO) confirmed
by an EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  UO crosses above 50 AND close > EMA200
Entry (short): UO crosses below 50 AND close < EMA200
Exit (long):   UO crosses below 50
Exit (short):  UO crosses above 50

The Ultimate Oscillator (Larry Williams, 1985) combines three
timeframes (7, 14, 28) with weighted averaging (4× short + 2×
medium + 1× long / 7) to reduce false divergence signals present
in single-timeframe oscillators.

Reference: Larry Williams — "The Ultimate Oscillator"
(Technical Analysis of Stocks & Commodities, 1985).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, ultimate_oscillator


class UltimateOscillatorTrend(Strategy):
    """Ultimate Oscillator with EMA200 trend filter.

    UO is a multi-timeframe momentum composite designed to reduce
    false divergence signals.  Entry requires UO crossing the 50
    centerline plus trend alignment (close vs EMA200).

    Parameters:
        uo_short: UO short period (default 7, weight 4).
        uo_medium: UO medium period (default 14, weight 2).
        uo_long: UO long period (default 28, weight 1).
        trend_period: EMA trend filter lookback (default 200).
    """

    timeframe = "1h"
    min_bars = 230  # uo_long(28) + trend_period(200) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "uo_short": 7,
        "uo_medium": 14,
        "uo_long": 28,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "UltimateOscillatorTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from UO cross + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        uo_short = self.params["uo_short"]
        uo_medium = self.params["uo_medium"]
        uo_long = self.params["uo_long"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        uo = ultimate_oscillator(
            df, short=uo_short, medium=uo_medium, long=uo_long
        )
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: UO > 50 + EMA trend)
        uo_above = uo > 50.0
        uo_below = uo < 50.0

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = uo_above & trend_up
        short_entry = uo_below & trend_down

        # Exit signals: UO crosses below/above 50
        exit_long = uo_below
        exit_short = uo_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(uo.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
