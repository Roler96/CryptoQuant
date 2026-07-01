"""Dual EMA Crossover + ATR Volatility Filter strategy.

Trend-following strategy using fast/slow EMA crossovers for entry, gated
by an ATR-based volatility filter. The volatility gate prevents entries
during turbulent markets where whipsaws are common.

Entry (long):  Fast EMA crosses ABOVE slow EMA AND ATR(14) < vol_threshold * ATR(50)
Entry (short): Fast EMA crosses BELOW slow EMA AND ATR(14) < vol_threshold * ATR(50)
Exit:          Reverse crossover (regardless of volatility filter)

Reference: arxiv 2511.00665 — EMA crossover benchmarked on Bitcoin post-ETF
data; ATR filter reduces ~30-40% of entries during high-volatility regimes.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, crossover, crossunder, ema


class EMACrossATRFilter(Strategy):
    """Dual EMA Crossover with ATR Volatility Filter.

    Parameters:
        fast_period: Fast EMA lookback (6-12 typical)
        slow_period: Slow EMA lookback (18-34 typical)
        atr_period: ATR short-term window
        atr_long_period: ATR long-term reference window
        vol_threshold: Max ATR ratio (short/long) for entry gating
    """

    timeframe = "1h"
    min_bars = 200  # slow_period * 2 + atr_long_period * 2, padded
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "fast_period": 8,
        "slow_period": 21,
        "atr_period": 14,
        "atr_long_period": 50,
        "vol_threshold": 2.0,
    }

    @property
    def name(self) -> str:
        return "EMACrossATRFilter"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from EMA crossover + ATR volatility filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        fast_period = self.params["fast_period"]
        slow_period = self.params["slow_period"]
        atr_period = self.params["atr_period"]
        atr_long_period = self.params["atr_long_period"]
        vol_threshold = self.params["vol_threshold"]

        # Compute indicators
        ema_fast = ema(close, period=fast_period)
        ema_slow = ema(close, period=slow_period)
        atr_short = atr(df, period=atr_period)
        atr_long = atr(df, period=atr_long_period)

        # Volatility gate: ATR(short) must be less than threshold * ATR(long)
        atr_ratio = atr_short / atr_long
        vol_ok = atr_ratio < vol_threshold

        # Entry signals (gated by volatility filter)
        long_cross = crossover(ema_fast, ema_slow).astype(bool)
        short_cross = crossunder(ema_fast, ema_slow).astype(bool)

        long_entry = long_cross & vol_ok
        short_entry = short_cross & vol_ok

        # Exit signals: reverse crossover, always applied regardless of vol
        exit_long = short_cross  # fast crosses below slow → exit long
        exit_short = long_cross  # fast crosses above slow → exit short

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_fast.iloc[i]) or pd.isna(ema_slow.iloc[i]):
                signal[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
