"""ADLineTrend strategy — A/D Line crossover + EMA200 trend filter.

Trend-following strategy using Accumulation/Distribution Line crossover
confirmed by EMA200 trend filter. Exactly 2 entry conditions.

Unlike OBV (which only uses sign(Δclose) × volume), A/D Line uses
close-position-within-bar weighting. Close near high → full volume added;
close near low → full volume subtracted. This makes it a hybrid of OBV's
cumulative property and position-based weighting — accumulated (noise
averages out) unlike raw CLV.

Entry (long):  A/D Line crosses above its SMA AND close > EMA200
Entry (short): A/D Line crosses below its SMA AND close < EMA200
Exit (long):   A/D Line crosses below its SMA(5) (fast reversal)
Exit (short):  A/D Line crosses above its SMA(5)

Reference: Marc Chaikin — "Technical Analysis from A to Z" (1995).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ad_line_sma, ema


class ADLineTrend(Strategy):
    """A/D Line crossover with EMA200 trend filter.

    Entry requires A/D Line crossover AND EMA200 alignment.
    Two conditions total.

    Parameters:
        ad_sma_long: SMA period for A/D Line signal (entry, default 20).
        ad_sma_short: SMA period for exit signal (default 5, faster).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(ad_sma_long, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ad_sma_long": 20,
        "ad_sma_short": 5,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ADLineTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from A/D Line crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        ad_sma_long = self.params["ad_sma_long"]
        ad_sma_short = self.params["ad_sma_short"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ad_df = ad_line_sma(df, period=ad_sma_long)
        ad_val = ad_df["ad_line"]
        ad_signal_long = ad_df["signal"]

        # Fast SMA for exit
        ad_signal_short = ema(ad_val, period=ad_sma_short)

        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: A/D Line crossover + EMA trend)
        ad_above_long = ad_val > ad_signal_long
        ad_below_long = ad_val < ad_signal_long

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = ad_above_long & trend_up
        short_entry = ad_below_long & trend_down

        # Exit: A/D Line crosses fast SMA
        ad_above_short = ad_val > ad_signal_short
        ad_below_short = ad_val < ad_signal_short
        exit_long = ad_below_short
        exit_short = ad_above_short

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(ad_val.iloc[i])
                or pd.isna(ad_signal_long.iloc[i])
                or pd.isna(ad_signal_short.iloc[i])
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
