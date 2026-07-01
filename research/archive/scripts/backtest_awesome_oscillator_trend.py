"""Awesome Oscillator Trend Following strategy.

Momentum trend-following strategy using Bill Williams' Awesome Oscillator (AO)
zero-line crossover confirmed by an EMA200 trend filter. Exactly 2 entry
conditions.

Entry (long):  AO crosses above 0 AND close > EMA(200)
Entry (short): AO crosses below 0 AND close < EMA(200)
Exit (long):   AO crosses below 0
Exit (short):  AO crosses above 0

AO = SMA(midpoint, 5) - SMA(midpoint, 34) where midpoint = (High + Low)/2.
Unlike RSI (smoothed), Stochastic (positional), and CMO (sum-based),
AO uses raw SMA of bar midpoints — a fundamentally different signal
generation mechanism. The midpoint averaging makes it potentially more
robust on ETH where close prices are influenced by fragmented liquidity.

Reference: Bill Williams — "Trading Chaos" (1995);
je-suis-tm/quant-trading (GitHub implementation).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, sma


class AwesomeOscillatorTrend(Strategy):
    """Awesome Oscillator zero-line crossover with EMA200 trend filter.

    Entry requires AO crossing zero AND trend alignment. Exit on AO
    reverse crossover. The AO uses bar midpoints, not closes, which
    reduces sensitivity to exchange-specific closing price noise.

    Parameters:
        ao_fast: Fast SMA period for AO (default 5)
        ao_slow: Slow SMA period for AO (default 34)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 300  # ao_slow + trend_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ao_fast": 5,
        "ao_slow": 34,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "AwesomeOscillatorTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from AO zero-line crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        ao_fast = self.params["ao_fast"]
        ao_slow = self.params["ao_slow"]
        trend_period = self.params["trend_period"]

        # Compute Awesome Oscillator: SMA(midpoint,5) - SMA(midpoint,34)
        midpoint = (df["high"] + df["low"]) / 2.0
        ao = sma(midpoint, period=ao_fast) - sma(midpoint, period=ao_slow)
        ao_prev = ao.shift(1)

        # Trend filter
        ema_trend = ema(close, period=trend_period)

        # Entry signals: AO zero-line crossover + EMA trend
        ao_cross_up = (ao > 0) & (ao_prev <= 0)
        ao_cross_down = (ao < 0) & (ao_prev >= 0)

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = ao_cross_up & trend_up
        short_entry = ao_cross_down & trend_down

        # Exit signals: AO crosses back across zero
        exit_long = ao_cross_down
        exit_short = ao_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ao.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
