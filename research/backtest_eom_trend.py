"""EOM Trend Following — Ease of Movement Zero-Cross with EMA200 Trend Filter.

Trend-following strategy using Richard Arms' Ease of Movement (EMV) indicator.
EMV measures how easily price moves per unit of volume — positive EMV means
price rises with low volume resistance (genuine buying pressure), negative
EMV means price falls easily (genuine selling pressure).

Exactly 2 entry conditions:
  - EMV zero-cross (signal direction shift)
  - Price vs EMA200 trend filter (align with long-term trend)

Entry (long):   EMV(14) crosses ABOVE 0 AND Close > EMA(200)
Entry (short):  EMV(14) crosses BELOW 0 AND Close < EMA(200)
Exit (long):    EMV(14) crosses BELOW 0
Exit (short):   EMV(14) crosses ABOVE 0

Reference: Richard Arms — "Volume Cycles in the Stock Market" (1994).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ease_of_movement, ema


class EOMTrend(Strategy):
    """Ease of Movement zero-cross with EMA200 trend filter.

    EMV normalizes price movement by volume, providing a volume-adjusted
    view of directional pressure.  Zero-crosses signal a shift in the
    dominant pressure direction.  The EMA200 filter ensures trades align
    with the primary trend.

    Parameters:
        emv_smooth: EMV smoothing period (default 14)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 250  # trend_period + EMV warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "emv_smooth": 14,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "EOMTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from EMV zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        emv_smooth = self.params["emv_smooth"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        emv = ease_of_movement(df, smooth=emv_smooth)
        ema_trend = ema(close, period=trend_period)

        # Zero-cross detection
        emv_above = emv > 0
        emv_below = emv < 0
        prev_above = emv_above.shift(1).fillna(False)
        prev_below = emv_below.shift(1).fillna(False)

        cross_up = emv_above & ~prev_above.astype(bool)
        cross_down = emv_below & ~prev_below.astype(bool)

        # Entry signals (2 conditions: EMV cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse EMV zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(emv.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
