"""Divergence Trend Following — RSI Divergence + EMA200 Filter.

Detects classic RSI divergence patterns (bullish/bearish) and enters
positions aligned with the EMA200 trend direction.  Exactly 2
conditions: divergence signal + EMA200 trend filter.

Entry (long):  RSI bullish divergence (price lower low, RSI higher low) + close > EMA200
Entry (short): RSI bearish divergence (price higher high, RSI lower high) + close < EMA200
Exit (long):   RSI reverse divergence
Exit (short):  RSI reverse divergence

RSI divergence is one of the most reliable reversal signals in technical
analysis, yet it often fails because people use the wrong lookback window.
The key: detect pivots using a rolling window of 14 bars, not the default 50.

Reference: Andrew Cardwell — RSI divergence primer.  The classic setup:
bull divergence = price makes a lower low while RSI makes a higher low.
bear divergence = price makes a higher high while RSI makes a lower high.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, rsi, rolling_max, rolling_min


class DivergenceTrend(Strategy):
    """RSI Divergence with EMA200 trend filter.

    Detects divergence between price action and RSI oscillator:
    - Bullish: price lower low, RSI higher low → long entry
    - Bearish: price higher high, RSI lower high → short entry

    Entry: divergence signal + EMA200 trend direction
    Exit:  reverse divergence (RSI cross)
    """

    timeframe = "1h"
    min_bars = 300  # warmup: 200 (trend) + 14 (RSI) + 14 (pivot)
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "rsi_period": 14,      # RSI calculation period
        "pivot_lookback": 14,  # pivot detection window (same as RSI period for simplicity)
        "trend_period": 200,   # EMA trend filter period
    }

    @property
    def name(self) -> str:
        return "DivergenceTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals: 1=long, -1=short, 0=flat."""
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        rsi_period = self.params["rsi_period"]
        pivot_lookback = self.params["pivot_lookback"]
        trend_period = self.params["trend_period"]

        # Compute RSI
        rsi_vals = rsi(close, period=rsi_period)

        # Detect pivot highs and lows
        pivot_high = rolling_max(df["high"], period=pivot_lookback)
        pivot_low = rolling_min(df["low"], period=pivot_lookback)

        # RSI at pivot points
        rsi_at_pivot_high = pd.Series(np.nan, index=df.index)
        rsi_at_pivot_low = pd.Series(np.nan, index=df.index)

        for i in range(pivot_lookback, len(df)):
            if not pd.isna(pivot_high.iloc[i]) and not pd.isna(pivot_low.iloc[i]):
                rsi_at_pivot_high.iloc[i] = rsi_vals.iloc[i]
                rsi_at_pivot_low.iloc[i] = rsi_vals.iloc[i]

        # Detect divergence
        # Bullish: price makes lower low and RSI makes higher low
        bullish_div = (rsi_at_pivot_low > rsi_at_pivot_high.shift(1).fillna(False)) & (
            pivot_low < pivot_high.shift(1).fillna(False)
        )
        # Mask out warmup bars (first pivot_lookback bars not meaningful)
        mask_warmup = pd.Series(True, index=df.index)
        mask_warmup.iloc[:pivot_lookback] = False
        bullish_div = bullish_div & mask_warmup

        # Bearish: price makes higher high and RSI makes lower high
        bearish_div = (rsi_at_pivot_high > rsi_at_pivot_low.shift(1).fillna(False)) & (
            pivot_high < pivot_low.shift(1).fillna(False)
        )
        bearish_div = bearish_div & mask_warmup

        # EMA200 trend
        ema_trend = ema(close, period=trend_period)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        # Entry signals
        long_entry = bullish_div & trend_up
        short_entry = bearish_div & trend_down

        # Exit signals
        exit_long = bearish_div
        exit_short = bullish_div

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    if short_entry.iloc[i]:
                        position = -1
                elif exit_short.iloc[i]:
                    position = 0
                    if long_entry.iloc[i]:
                        position = 1

            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    if short_entry.iloc[i]:
                        position = -1
                elif exit_long.iloc[i]:
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
