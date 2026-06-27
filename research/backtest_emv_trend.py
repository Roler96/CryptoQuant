"""EMVTrend strategy — Ease of Movement zero-cross + EMA200 trend filter.

Trend-following strategy using Ease of Movement (EMV) zero-cross
confirmed by EMA200 trend filter. Exactly 2 entry conditions.

EMV measures how much price moved relative to the volume required to
move it. High EMV → price moves easily (low friction). Low EMV →
price struggles (high friction/chop). This is fundamentally different
from OBV and ADLine — EMV directly measures market friction, a
regime-sensitive signal that no previous strategy has tested.

Entry (long):  EMV crosses above zero AND close > EMA200
Entry (short): EMV crosses below zero AND close < EMA200
Exit (long):   EMV crosses below zero
Exit (short):  EMV crosses above zero

Reference: Richard Arms — "Volume Cycles in the Stock Market" (1994).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ease_of_movement, ema


class EMVTrend(Strategy):
    """Ease of Movement zero-cross with EMA200 trend filter.

    Entry requires EMV zero-cross AND EMA200 alignment.
    Two conditions total.

    Parameters:
        emv_smooth: EMA smoothing period for EMV (default 5).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # trend_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "emv_smooth": 5,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "EMVTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from EMV zero-cross + EMA trend.

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
        emv_val = ease_of_movement(df, smooth=emv_smooth)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: EMV crosses zero + EMA trend)
        emv_above_zero = emv_val > 0
        emv_below_zero = emv_val < 0

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = emv_above_zero & trend_up
        short_entry = emv_below_zero & trend_down

        # Exit: EMV crosses back through zero
        exit_long = emv_below_zero
        exit_short = emv_above_zero

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(emv_val.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
