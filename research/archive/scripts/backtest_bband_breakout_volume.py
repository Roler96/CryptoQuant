"""Bollinger Band Breakout with Volume Confirmation strategy.

Volatility-breakout strategy: enters when price pierces the Bollinger Band
envelope with above-average volume. Exits when price returns to the BB
middle band. This is a volatility-expansion entry, orthogonal to EMA
crossover strategies.

Entry (long):  close > BB_upper(20, 2.0) AND volume > SMA(volume, 20)
Entry (short): close < BB_lower(20, 2.0) AND volume > SMA(volume, 20)
Exit (long):  close < BB_middle (SMA 20)
Exit (short): close > BB_middle (SMA 20)

Reference: Bollinger Band breakout literature (TradingView, QuantConnect).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import bollinger_bands, volume_sma


class BBandBreakoutVolume(Strategy):
    """Bollinger Band Breakout with Volume Confirmation.

    Parameters:
        bb_period: Bollinger Band lookback (default 20)
        bb_std: Standard deviation multiplier (default 2.0)
        vol_period: Volume SMA lookback (default 20)
    """

    timeframe = "1h"
    min_bars = 100  # 2 × max(bb_period, vol_period), padded
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "vol_period": 20,
    }

    @property
    def name(self) -> str:
        return "BBandBreakoutVolume"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from BB breakout + volume confirmation.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        vol_period = self.params["vol_period"]

        # Compute indicators
        bb = bollinger_bands(df, period=bb_period, std=bb_std)
        bb_upper = bb["upper"]
        bb_lower = bb["lower"]
        bb_middle = bb["middle"]
        vol_sma_series = volume_sma(df, period=vol_period)

        # Volume confirmation: volume > SMA(volume)
        vol_ok: pd.Series = df["volume"] > vol_sma_series  # type: ignore[assignment]

        # Entry signals (close breaches BB envelope + volume confirms)
        long_entry = (close > bb_upper) & vol_ok
        short_entry = (close < bb_lower) & vol_ok

        # Exit signals: close crosses back inside BB middle
        exit_long = close < bb_middle
        exit_short = close > bb_middle

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(bb_middle.iloc[i]):
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
