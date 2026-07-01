"""Donchian ATR Breakout — Turtle Channel + ATR Expansion Confirmation.

Trend-following strategy using 20-bar Donchian Channel breakout
confirmed by ATR expansion.  Exactly 2 entry conditions.

Entry (long):  Close > highest(high, lookback) AND ATR > SMA(ATR, atr_ma)
Entry (short): Close < lowest(low, lookback) AND ATR > SMA(ATR, atr_ma)
Exit (long):   Close < lowest(low, lookback)
Exit (short):  Close > highest(high, lookback)

Based on the breakout template proven in Loops 5/6/13/18 (RangeExpansionBreakout,
InsideBarBreakout, PSARTrend, BBPercentBVolatility).  Prior Donchian test
(DonchianEnsemble, Loop 1) failed because 7-channel binomial voting created
3+ effective AND conditions.  This standalone version uses exactly 2: breakout
+ expansion.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, sma, rolling_max, rolling_min


class DonchianATRBreakout(Strategy):
    """Donchian Channel breakout with ATR expansion confirmation.

    Entry requires both:
    1. Close breaches channel boundary (new 20-bar high/low)
    2. ATR(14) exceeds its 50-period SMA (volatility expansion)

    Exit: reverse breakout — close breaches opposite channel boundary.

    Parameters:
        lookback: Donchian Channel period (default 20).
        atr_period: ATR smoothing period (default 14).
        atr_ma_period: SMA period for ATR expansion check (default 50).
    """

    timeframe = "1h"
    min_bars = 60
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lookback": 20,
        "atr_period": 14,
        "atr_ma_period": 50,
    }

    @property
    def name(self) -> str:
        return "DonchianATRBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Donchian Channel breakout + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]  # type: ignore[assignment]
        low: pd.Series = df["low"]  # type: ignore[assignment]

        lookback = self.params["lookback"]
        atr_period = self.params["atr_period"]
        atr_ma_period = self.params["atr_ma_period"]

        # Donchian Channel boundaries
        upper = rolling_max(high, lookback)
        lower = rolling_min(low, lookback)

        # ATR expansion filter
        atr_val = atr(df, period=atr_period)
        atr_sma = sma(atr_val, period=atr_ma_period)
        expansion = atr_val > atr_sma

        # Entry conditions (exactly 2 AND gates)
        breakout_up = close > upper.shift(1)
        breakout_down = close < lower.shift(1)

        long_entry = breakout_up & expansion
        short_entry = breakout_down & expansion

        # Exit: reverse breakout
        exit_long = close < lower.shift(1)
        exit_short = close > upper.shift(1)

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(upper.iloc[i]):
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
