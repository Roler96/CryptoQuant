"""Parabolic SAR Trend Following strategy.

Trend-following strategy using Parabolic SAR cross confirmed by an
EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  close > PSAR AND close > EMA200
Entry (short): close < PSAR AND close < EMA200
Exit (long):   close < PSAR (SAR reverses)
Exit (short):  close > PSAR (SAR reverses)

PSAR is fundamentally different from oscillators and breakout-based
entries — it's acceleration-based. Combined with a simple EMA trend
filter, it provides clean entries during genuine trend development.

Reference: Welles Wilder — New Concepts in Technical Trading Systems
(1978); je-suis-tm/quant-trading (GitHub implementation).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, psar


class PsarTrend(Strategy):
    """Parabolic SAR with EMA200 trend filter.

    Parabolic SAR acts as a dynamic stop-and-reverse indicator. When
    price crosses above PSAR, it signals a trend reversal to bullish.
    Entry requires both PSAR cross and trend alignment (close vs EMA200).

    Parameters:
        psar_af_start: PSAR acceleration factor start (default 0.02)
        psar_af_step: PSAR acceleration factor step (default 0.02)
        psar_af_max: PSAR acceleration factor max (default 0.20)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 300  # trend_period + PSAR warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "psar_af_start": 0.02,
        "psar_af_step": 0.02,
        "psar_af_max": 0.20,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "PsarTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from PSAR crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        psar_af_start = self.params["psar_af_start"]
        psar_af_step = self.params["psar_af_step"]
        psar_af_max = self.params["psar_af_max"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        psar_vals = psar(
            df,
            af_start=psar_af_start,
            af_step=psar_af_step,
            af_max=psar_af_max,
        )
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: PSAR position + EMA trend)
        above_psar = close > psar_vals
        below_psar = close < psar_vals

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = above_psar & trend_up
        short_entry = below_psar & trend_down

        # Exit signals: price crosses PSAR (reverse signal)
        exit_long = below_psar
        exit_short = above_psar

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(psar_vals.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
