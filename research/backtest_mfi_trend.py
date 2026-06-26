"""Money Flow Index Trend Following strategy.

Trend-following strategy using the Money Flow Index (MFI) midline
cross confirmed by an EMA200 trend filter.  Exactly 2 entry conditions.

Entry (long):  MFI crosses ABOVE 50 AND close > EMA200
Entry (short): MFI crosses BELOW 50 AND close < EMA200
Exit (long):   MFI crosses BELOW 50
Exit (short):  MFI crosses ABOVE 50

MFI is a volume-weighted RSI on a 0-100 normalized scale — proven
universal across all timeframes (BB %B lesson).  Volume is a signal-
weight multiplier in MFI's internal formula, not an AND gate.

Reference: Gene Quong & Avrum Soudack (1989).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, mfi


class MFITrend(Strategy):
    """MFI midline cross with EMA200 trend filter.

    Money Flow Index combines price change direction with volume magnitude
    into a normalized 0-100 oscillator.  Crossing the 50 midline signals
    a shift from accumulation (50+) to distribution (50-) or vice versa.
    Entry requires both the midline cross AND price trend alignment.

    Parameters:
        mfi_period: MFI lookback period (default 14)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period + MFI warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "mfi_period": 14,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "MFITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from MFI midline crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        mfi_period = self.params["mfi_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        mfi_val = mfi(df, period=mfi_period)
        ema_trend = ema(close, period=trend_period)

        # Midline (50) cross detection
        mfi_above_50 = mfi_val > 50
        mfi_below_50 = mfi_val < 50
        prev_above = mfi_above_50.shift(1).fillna(False)
        prev_below = mfi_below_50.shift(1).fillna(False)

        cross_up = mfi_above_50 & ~prev_above.astype(bool)
        cross_down = mfi_below_50 & ~prev_below.astype(bool)

        # Entry signals (2 conditions: MFI cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse MFI midline cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(mfi_val.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
