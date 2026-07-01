"""Williams %R Trend Following strategy.

Trend-following strategy using Williams %R midline crossover
confirmed by EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  %R(14) crosses above -50 AND close > EMA200
Entry (short): %R(14) crosses below -50 AND close < EMA200
Exit (long):   %R crosses below -50
Exit (short):  %R crosses above -50

Williams %R is a raw, unsmoothed oscillator (-100 to 0) — faster
than Stochastic (%K/%D Wilder smoothing) and closer to CCI in
responsiveness. The midline (-50) cross generates more signals than
extreme thresholds (-20/-80), targeting 120-200 trades/year on 1h.

Reference: Larry Williams — "How I Made One Million Dollars Last
Year Trading Commodities" (1979).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, williams_r


class WilliamsRTrend(Strategy):
    """Williams %R midline crossover with EMA200 trend filter.

    Entry requires %R crossing midline (-50) in the direction
    of the trade PLUS EMA200 trend alignment.  Two conditions total.

    Parameters:
        wr_period: Williams %R lookback (default 14).
        trend_period: EMA trend filter period (default 200).
        entry_threshold: Midline for %R cross (default -50).
    """

    timeframe = "1h"
    min_bars = 210  # max(wr_period, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "wr_period": 14,
        "trend_period": 200,
        "entry_threshold": -50,
    }

    @property
    def name(self) -> str:
        return "WilliamsRTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Williams %R crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        wr_period = self.params["wr_period"]
        trend_period = self.params["trend_period"]
        entry_threshold = self.params["entry_threshold"]

        # Compute indicators
        wr = williams_r(df, period=wr_period)
        ema_trend = ema(close, period=trend_period)

        # Entry: %R crosses above/below midline + trend confirmation
        wr_above = wr > entry_threshold
        wr_below = wr < entry_threshold

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = wr_above & trend_up
        short_entry = wr_below & trend_down

        # Exit: %R crosses back across midline
        exit_long = wr_below
        exit_short = wr_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(wr.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
