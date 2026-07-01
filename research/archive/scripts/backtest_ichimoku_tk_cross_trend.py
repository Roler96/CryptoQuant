"""Ichimoku TK Cross Trend Following strategy.

Trend-following strategy using Ichimoku Tenkan-sen / Kijun-sen crossover
confirmed by an EMA trend filter. Exactly 2 entry conditions.

Unlike Loop 9's IchimokuCloud (which required 3 conditions including the
dual cloud span filter), this strategy uses only TK cross + trend filter.

Tenkan-sen = (Highest High + Lowest Low) / 2 over tenkan_period bars.
Kijun-sen  = (Highest High + Lowest Low) / 2 over kijun_period bars.

Entry (long):  Tenkan-sen > Kijun-sen (bullish TK cross) AND close > EMA200
Entry (short): Tenkan-sen < Kijun-sen (bearish TK cross) AND close < EMA200
Exit:          Tenkan-sen crosses back through Kijun-sen

Reference: Goichi Hosoda — Ichimoku Kinko Hyo (1969).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


def tenkan_sen(df: pd.DataFrame, period: int = 9) -> pd.Series:
    """Compute Ichimoku Tenkan-sen (Conversion Line).

    (Highest High + Lowest Low) / 2 over `period` bars.
    """
    highest = df["high"].rolling(period).max()
    lowest = df["low"].rolling(period).min()
    return (highest + lowest) / 2


def kijun_sen(df: pd.DataFrame, period: int = 26) -> pd.Series:
    """Compute Ichimoku Kijun-sen (Base Line).

    (Highest High + Lowest Low) / 2 over `period` bars.
    """
    highest = df["high"].rolling(period).max()
    lowest = df["low"].rolling(period).min()
    return (highest + lowest) / 2


class IchimokuTKCrossTrend(Strategy):
    """Ichimoku TK crossover with EMA trend filter.

    Uses only Tenkan-sen / Kijun-sen (TK) crossover as the entry trigger.
    No cloud filter (Senkou Span A/B) — this avoids the disguised
    3-condition entry that caused IchimokuCloud (Loop 9) to fail.

    Parameters:
        tenkan_period: Tenkan-sen lookback (default 9)
        kijun_period: Kijun-sen lookback (default 26)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # kijun_period + trend_period warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "tenkan_period": 9,
        "kijun_period": 26,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "IchimokuTKCrossTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TK cross + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        tenkan_p = self.params["tenkan_period"]
        kijun_p = self.params["kijun_period"]
        trend_p = self.params["trend_period"]

        # Compute indicators
        tk = tenkan_sen(df, period=tenkan_p)
        kj = kijun_sen(df, period=kijun_p)
        ema_trend = ema(close, period=trend_p)

        # TK cross detection
        tk_above = tk > kj
        tk_below = tk < kj
        prev_above = tk_above.shift(1).fillna(False)
        prev_below = tk_below.shift(1).fillna(False)

        # Tenkan crosses above Kijun → bullish momentum
        tk_cross_up = tk_above & ~prev_above.astype(bool)  # type: ignore[operator]
        # Tenkan crosses below Kijun → bearish momentum
        tk_cross_down = tk_below & ~prev_below.astype(bool)  # type: ignore[operator]

        # Trend filters (2 conditions: TK cross + trend alignment)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = tk_cross_up & trend_up
        short_entry = tk_cross_down & trend_down

        exit_long = tk_cross_down
        exit_short = tk_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(tk.iloc[i]) or pd.isna(kj.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
