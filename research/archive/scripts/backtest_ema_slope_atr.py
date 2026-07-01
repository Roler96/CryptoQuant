"""EMA Slope + ATR Expansion strategy.

Uses EMA(20) slope acceleration as a trend-strength proxy paired with
ATR expansion for volatility confirmation. Exactly 2 entry conditions.

Entry (long):  EMA(20) slope accelerating (current slope > slope N bars ago)
               AND ATR(14) > SMA(ATR(14), 50) — volatility expansion
Entry (short): EMA(20) slope decelerating (current slope < slope N bars ago)
               AND ATR(14) > SMA(ATR(14), 50)
Exit (long):   Slope crosses below zero (trend lost)
Exit (short):  Slope crosses above zero (trend lost)

Slope = EMA(20)[t] - EMA(20)[t-1] — first derivative of EMA.
Acceleration = slope > slope N bars ago (second derivative).

This is a 2-condition strategy: slope direction change + ATR expansion.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, ema, sma


class EMASlopeATR(Strategy):
    """EMA slope acceleration with ATR volatility confirmation.

    Parameters:
        ema_period: Period for EMA whose slope is measured (default 20)
        slope_lookback: Bars to compare slope against (default 5)
        atr_period: Period for ATR calculation (default 14)
        atr_ma_period: Period for ATR moving average baseline (default 50)
    """

    timeframe = "1h"
    min_bars = 200  # atr_ma_period * 4 for statistical stability
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ema_period": 20,
        "slope_lookback": 5,
        "atr_period": 14,
        "atr_ma_period": 50,
    }

    @property
    def name(self) -> str:
        return "EMASlopeATR"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from EMA slope acceleration + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        ema_period = self.params["ema_period"]
        slope_lookback = self.params["slope_lookback"]
        atr_period = self.params["atr_period"]
        atr_ma_period = self.params["atr_ma_period"]

        # Compute indicators
        ema_line = ema(close, period=ema_period)
        ema_slope = ema_line.diff()  # first derivative

        # Slope lookback comparison
        slope_prev = ema_slope.shift(slope_lookback)

        # ATR expansion: current ATR > SMA of ATR
        atr_val = atr(df, period=atr_period)
        atr_baseline = sma(atr_val, period=atr_ma_period)
        atr_expanding = atr_val > atr_baseline

        # Slope direction: positive = uptrend, negative = downtrend
        slope_accelerating = ema_slope > slope_prev  # long signal
        slope_decelerating = ema_slope < slope_prev  # short signal

        # Entry signals: 2 conditions
        long_entry = slope_accelerating & atr_expanding
        short_entry = slope_decelerating & atr_expanding

        # Exit: slope crosses zero
        exit_long = ema_slope <= 0
        exit_short = ema_slope >= 0

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(atr_val.iloc[i]) or pd.isna(atr_baseline.iloc[i]) or pd.isna(ema_slope.iloc[i]):
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
