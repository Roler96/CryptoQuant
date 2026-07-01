"""ChaikinOscillatorTrend strategy — Chaikin Oscillator zero-cross + EMA200.

Trend-following strategy using Chaikin Oscillator zero-cross confirmed
by EMA200 trend filter. Exactly 2 entry conditions.

Chaikin Oscillator = EMA(3, A/D Line) − EMA(10, A/D Line) measures the
momentum of accumulation/distribution. Positive oscillator means buying
pressure is accelerating (precedes upward price). Negative oscillator
means distribution is accelerating (precedes downward price).

The Chaikin Oscillator fires MORE frequently than OBV crossover because
it measures rate-of-change of accumulation, not just direction — the
zero-cross is an earlier signal than OBV SMA crossover.

Entry (long):  Chaikin Oscillator crosses above 0 AND close > EMA200
Entry (short): Chaikin Oscillator crosses below 0 AND close < EMA200
Exit:          Chaikin Oscillator crosses opposite direction OR
               trailing stop at 2× ATR(14)

Reference: Marc Chaikin — "Technical Analysis from A to Z" (1995).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    atr,
    chaikin_oscillator,
    ema,
)


class ChaikinOscillatorTrend(Strategy):
    """Chaikin Oscillator zero-cross with EMA200 trend filter.

    Entry requires Chaikin Oscillator zero-cross AND EMA200 alignment.
    Two conditions total.

    Parameters:
        chaikin_fast: Fast EMA period for Chaikin Oscillator (default 3).
        chaikin_slow: Slow EMA period for Chaikin Oscillator (default 10).
        trend_period: EMA trend filter period (default 200).
        atr_period: ATR period for trailing stop (default 14).
        trailing_mult: ATR multiplier for trailing stop (default 2.0).
    """

    timeframe = "1h"
    min_bars = 210  # max(chaikin_slow, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "chaikin_fast": 3,
        "chaikin_slow": 10,
        "trend_period": 200,
        "atr_period": 14,
        "trailing_mult": 2.0,
    }

    @property
    def name(self) -> str:
        return "ChaikinOscillatorTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Chaikin Oscillator zero-cross + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        chaikin_fast = self.params["chaikin_fast"]
        chaikin_slow = self.params["chaikin_slow"]
        trend_period = self.params["trend_period"]
        atr_period = self.params["atr_period"]
        trailing_mult = self.params["trailing_mult"]

        # Compute indicators
        co = chaikin_oscillator(df, fast=chaikin_fast, slow=chaikin_slow)
        ema_trend = ema(close, period=trend_period)
        atr_val = atr(df, period=atr_period)

        # Entry signals (2 conditions: Chaikin zero-cross + EMA trend)
        co_above = co > 0.0
        co_below = co < 0.0
        co_prev_above = co.shift(1) > 0.0
        co_prev_below = co.shift(1) < 0.0

        long_entry = co_above & ~co_prev_above & (close > ema_trend)
        short_entry = co_below & ~co_prev_below & (close < ema_trend)

        # Exit: Chaikin crosses opposite zero
        exit_long = co_below & ~co_prev_below
        exit_short = co_above & ~co_prev_above

        # Stateful signal generation with trailing stop
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short
        entry_price = 0.0
        trail_stop: float = float("inf")

        for i in range(n):
            if (
                pd.isna(co.iloc[i])
                or pd.isna(ema_trend.iloc[i])
                or pd.isna(atr_val.iloc[i])
            ):
                signal_arr[i] = 0
                continue

            bar_high = df["high"].iloc[i]
            bar_low = df["low"].iloc[i]

            if position == 1:
                # Update trailing stop (highest high minus ATR multiplier)
                if close.iloc[i] > entry_price:
                    trail_stop = min(
                        trail_stop, close.iloc[i] - trailing_mult * atr_val.iloc[i]
                    )
                else:
                    trail_stop = min(
                        trail_stop,
                        entry_price - trailing_mult * atr_val.iloc[i],
                    )

                # Exit on trailing stop hit or Chaikin crossunder
                exited = False
                if bar_low <= trail_stop:
                    position = 0
                    exited = True
                elif exit_long.iloc[i]:
                    position = 0
                    exited = True

                if exited and short_entry.iloc[i] and bar_high > trail_stop:
                    position = -1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] + trailing_mult * atr_val.iloc[i]

            elif position == -1:
                # Update trailing stop (lowest low plus ATR multiplier)
                if close.iloc[i] < entry_price:
                    trail_stop = max(
                        trail_stop, close.iloc[i] + trailing_mult * atr_val.iloc[i]
                    )
                else:
                    trail_stop = max(
                        trail_stop,
                        entry_price + trailing_mult * atr_val.iloc[i],
                    )

                # Exit on trailing stop hit or Chaikin crossover
                exited = False
                if bar_high >= trail_stop:
                    position = 0
                    exited = True
                elif exit_short.iloc[i]:
                    position = 0
                    exited = True

                if exited and long_entry.iloc[i] and bar_low < trail_stop:
                    position = 1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] - trailing_mult * atr_val.iloc[i]

            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] - trailing_mult * atr_val.iloc[i]
                elif short_entry.iloc[i]:
                    position = -1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] + trailing_mult * atr_val.iloc[i]

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
