"""STC Trend Following strategy.

Trend-following strategy using Schaff Trend Cycle (STC) oscillator
threshold + EMA200 trend filter. Exactly 2 entry conditions.

STC = Stochastic(MACD(23,50), 10) — a double-smoothed 0-100 oscillator
that turns faster than MACD by applying the Stochastic %K formula to
the MACD line.

Entry (long):  STC > 25 AND close > EMA200
Entry (short): STC < 75 AND close < EMA200
Exit (long):   STC < 50 (momentum neutral)
Exit (short):  STC > 50

Reference: Doug Schaff — "Schaff Trend Cycle" (1999).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, stc


class STCTrend(Strategy):
    """Schaff Trend Cycle threshold with EMA200 trend filter.

    STC is a composite oscillator that applies the Stochastic formula to
    the MACD line, producing faster turning points. Entry requires STC
    crossing extreme thresholds AND price trend alignment (EMA200).

    Parameters:
        stc_fast: MACD fast EMA period (default 23)
        stc_slow: MACD slow EMA period (default 50)
        stc_cycle: STC %K normalization lookback (default 10)
        stc_d_period: STC final smoothing (default 3)
        stc_entry: STC threshold for long entry (default 25)
        stc_short_entry: STC threshold for short entry (default 75)
        stc_exit: STC midline for exit (default 50)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period(200) + warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "stc_fast": 23,
        "stc_slow": 50,
        "stc_cycle": 10,
        "stc_d_period": 3,
        "stc_entry": 25,
        "stc_short_entry": 75,
        "stc_exit": 50,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "STCTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from STC thresholds + EMA200 trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        stc_fast = self.params["stc_fast"]
        stc_slow = self.params["stc_slow"]
        stc_cycle = self.params["stc_cycle"]
        stc_d_period = self.params["stc_d_period"]
        stc_entry = self.params["stc_entry"]
        stc_short = self.params["stc_short_entry"]
        stc_exit = self.params["stc_exit"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        stc_val = stc(df, fast=stc_fast, slow=stc_slow, cycle=stc_cycle, d_period=stc_d_period)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: STC threshold + EMA200 trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        # Cross-based entry: STC crosses above/below threshold
        stc_above_entry = stc_val > stc_entry
        stc_below_short = stc_val < stc_short

        long_entry = stc_above_entry & trend_up
        short_entry = stc_below_short & trend_down

        # Exit signals: STC crosses midline
        exit_long = stc_val < stc_exit
        exit_short = stc_val > stc_exit

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(stc_val.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
