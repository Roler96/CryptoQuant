"""Dual Thrust Breakout strategy.

Classic range-based breakout strategy developed by Michael Chalek (1980s).
Uses ATR-based adaptive range to set upper/lower breakout bounds, confirmed
by an EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  close > Open + K1 * Range(N) AND close > EMA(200)
Entry (short): close < Open - K2 * Range(N) AND close < EMA(200)
Exit (long):   close crosses below opposite bound
Exit (short):  close crosses above opposite bound

The range is computed as the maximum of (high-low) over the lookback period,
providing an ATR-like adaptive bound that doesn't grow with trend direction.
This adaptation makes it suitable for crypto's higher volatility compared to
the original Dual Thrust (which uses HH-LC/HC-LL range for equities).

Reference: Michael Chalek — Dual Thrust Trading System (1980s);
je-suis-tm/quant-trading (GitHub implementation, adapted for crypto).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class DualThrustBreakout(Strategy):
    """Dual Thrust breakout with EMA200 trend filter.

    Entry requires price breakout above/below ATR-based range bounds
    AND alignment with the long-term trend. Exit on reverse breakout.

    Parameters:
        lookback: Range calculation period (default 20)
        k1: Upper bound coefficient (default 0.3)
        k2: Lower bound coefficient (default 0.3)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 300  # trend_period + lookback + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lookback": 20,
        "k1": 0.3,
        "k2": 0.3,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "DualThrustBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Dual Thrust breakout + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        open_: pd.Series = df["open"]  # type: ignore[assignment]

        lookback = self.params["lookback"]
        k1 = self.params["k1"]
        k2 = self.params["k2"]
        trend_period = self.params["trend_period"]

        # Compute range: max(high-low) over lookback period
        # This acts like a trailing ATR — adapts to volatility without trending
        bar_range = df["high"] - df["low"]
        range_val = bar_range.rolling(lookback).max().shift(1)

        # Bounds at bar open
        upper_bound = open_ + k1 * range_val
        lower_bound = open_ - k2 * range_val

        # Trend filter
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: breakout + EMA trend)
        above_upper = close > upper_bound
        below_lower = close < lower_bound

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = above_upper & trend_up
        short_entry = below_lower & trend_down

        # Exit signals: price crosses opposite bound
        exit_long = below_lower
        exit_short = above_upper

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(range_val.iloc[i]) or pd.isna(ema_trend.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip to short
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip to long
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
