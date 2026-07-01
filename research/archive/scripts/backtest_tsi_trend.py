"""TSI (True Strength Index) Trend Following strategy.

Trend-following strategy using TSI zero-cross confirmed by an
EMA200 trend filter. Exactly 2 entry conditions.

TSI = 100 * EMA(EMA(Δp, short), long) / EMA(EMA(|Δp|, short), long)

Entry (long):  TSI crosses above 0 AND close > EMA200
Entry (short): TSI crosses below 0 AND close < EMA200
Exit (long):   TSI crosses below 0 (momentum turns negative)
Exit (short):  TSI crosses above 0 (momentum turns positive)

TSI's double-EMA smoothing on both numerator and denominator produces
cleaner zero-crosses than single-smoothed oscillators (RSI, Stochastic,
CCI), making it a robust momentum-based entry with minimal whiplash.

Reference: William Blau — "The True Strength Index"
(Stocks & Commodities, 1991).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, tsi


class TSITrend(Strategy):
    """True Strength Index with EMA200 trend filter.

    Parameters:
        tsi_short: TSI short EMA period (default 13)
        tsi_long: TSI long EMA period (default 25)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 300  # trend_period + TSI warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "tsi_short": 13,
        "tsi_long": 25,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "TSITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TSI zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        tsi_short = self.params["tsi_short"]
        tsi_long = self.params["tsi_long"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        tsi_df = tsi(close, short_period=tsi_short, long_period=tsi_long)
        tsi_vals = tsi_df["tsi"]
        ema_trend = ema(close, period=trend_period)

        # Zero-cross detection
        tsi_above_zero = tsi_vals > 0
        tsi_below_zero = tsi_vals < 0
        tsi_prev_above = tsi_above_zero.shift(1).fillna(False).astype(bool)
        tsi_prev_below = tsi_below_zero.shift(1).fillna(False).astype(bool)

        cross_above_zero = tsi_above_zero & ~tsi_prev_above
        cross_below_zero = tsi_below_zero & ~tsi_prev_below

        # Trend direction
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        # Entry signals (2 conditions: TSI zero-cross + EMA trend)
        long_entry = cross_above_zero & trend_up
        short_entry = cross_below_zero & trend_down

        # Exit signals
        exit_long = cross_below_zero
        exit_short = cross_above_zero

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(tsi_vals.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
