"""Price Channel Breakout with RSI Momentum Confirmation strategy.

Trend-following strategy using a Donchian-style price channel breakout
confirmed by RSI momentum. Breaking the N-period high signals intent,
but RSI > 50 filters out marginal breakouts lacking momentum.

Entry (long):  close > highest(high, 30) AND RSI(14) > 50
Entry (short): close < lowest(low, 30) AND RSI(14) < 50
Exit (long):  close < SMA(close, 20)
Exit (short): close > SMA(close, 20)

Reference: Donchian Channel + RSI filter (QuantConnect, TradingView).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import rsi, rolling_max, rolling_min, sma


class ChannelBreakoutRSI(Strategy):
    """Price Channel Breakout with RSI Momentum Confirmation.

    Parameters:
        channel_period: Donchian channel lookback (default 30)
        rsi_period: RSI lookback (default 14)
        rsi_threshold: RSI direction threshold (default 50)
        sma_period: SMA trend exit lookback (default 20)
    """

    timeframe = "1h"
    min_bars = 100  # 2 × max(channel_period, rsi_period, sma_period), padded
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "channel_period": 30,
        "rsi_period": 14,
        "rsi_threshold": 50,
        "sma_period": 20,
    }

    @property
    def name(self) -> str:
        return "ChannelBreakoutRSI"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from channel breakout + RSI confirmation.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]  # type: ignore[assignment]
        low: pd.Series = df["low"]  # type: ignore[assignment]

        channel_period = self.params["channel_period"]
        rsi_period = self.params["rsi_period"]
        rsi_threshold = self.params["rsi_threshold"]
        sma_period = self.params["sma_period"]

        # Compute indicators
        highest_high = rolling_max(high, period=channel_period).shift(1)
        lowest_low = rolling_min(low, period=channel_period).shift(1)
        rsi_series = rsi(close, period=rsi_period)
        sma_series = sma(close, period=sma_period)

        # Entry signals
        long_entry = (close > highest_high) & (rsi_series > rsi_threshold)
        short_entry = (close < lowest_low) & (rsi_series < rsi_threshold)

        # Exit signals: close crosses SMA
        exit_long = close < sma_series
        exit_short = close > sma_series

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(highest_high.iloc[i]) or pd.isna(rsi_series.iloc[i]):
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
