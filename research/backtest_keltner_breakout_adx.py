"""Keltner Channel Breakout with ADX + Volume Confirmation.

Trend-following breakout strategy using Keltner Channel (EMA ± ATR multiplier),
confirmed by ADX trend strength and volume expansion. Targets directional moves
while filtering out fakeouts via dual confirmation from ADX and volume.

Entry (long):  Close > KC upper band AND ADX > threshold AND volume ratio > threshold
Entry (short): Close < KC lower band AND ADX > threshold AND volume ratio > threshold
Exit:          Close crosses back to KC middle band (EMA)
Stop-loss:     multiplier × ATR from entry
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import adx, atr, ema, volume_profile_ratio


class KeltnerBreakoutADX(Strategy):
    """Keltner Channel Breakout with ADX + Volume Confirmation.

    Parameters:
        kc_period: EMA period for Keltner Channel centerline
        kc_multiplier: ATR multiplier for band width
        atr_period: ATR lookback period
        adx_period: ADX lookback period
        adx_threshold: Minimum ADX for trend confirmation
        vol_period: Volume SMA period
        vol_threshold: Volume ratio threshold
        stop_atr_mult: Stop-loss in ATR multiples
    """

    timeframe = "1h"
    min_bars = 100  # generous pad over max(adx_period=14, kc_period=20, vol_period=20)
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "kc_period": 20,
        "kc_multiplier": 2.0,
        "atr_period": 14,
        "adx_period": 14,
        "adx_threshold": 22,
        "vol_period": 20,
        "vol_threshold": 1.2,
        "stop_atr_mult": 2.5,
    }

    @property
    def name(self) -> str:
        return "KeltnerBreakoutADX"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Keltner Channel breakout + ADX + volume.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        kc_period = self.params["kc_period"]
        kc_mult = self.params["kc_multiplier"]
        atr_period = self.params["atr_period"]
        adx_period = self.params["adx_period"]
        adx_threshold = self.params["adx_threshold"]
        vol_period = self.params["vol_period"]
        vol_threshold = self.params["vol_threshold"]

        # Compute indicators
        kc_middle = ema(close, period=kc_period)
        atr_val = atr(df, period=atr_period)
        kc_upper = kc_middle + kc_mult * atr_val
        kc_lower = kc_middle - kc_mult * atr_val

        adx_df = adx(df, period=adx_period)
        adx_val = adx_df["adx"]

        vol_ratio = volume_profile_ratio(df, period=vol_period)

        # Entry conditions
        breakout_long = close > kc_upper
        breakout_short = close < kc_lower
        trend_ok = adx_val > adx_threshold
        vol_ok = vol_ratio > vol_threshold

        long_entry = breakout_long & trend_ok & vol_ok
        short_entry = breakout_short & trend_ok & vol_ok

        # Exit: close returns inside Keltner Channel (crosses middle band)
        exit_long = close < kc_middle
        exit_short = close > kc_middle

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(kc_middle.iloc[i]) or pd.isna(adx_val.iloc[i]):
                signal[i] = 0
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

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
