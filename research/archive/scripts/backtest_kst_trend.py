"""KST Trend Following strategy.

Trend-following strategy using KST (Know Sure Thing) crossover
confirmed by EMA200 trend filter.  Exactly 2 entry conditions.

Entry (long):  KST crosses above signal line AND close > EMA200
Entry (short): KST crosses below signal line AND close < EMA200
Exit (long):   KST crosses below signal line
Exit (short):  KST crosses above signal line

KST (Martin Pring) sums four Rate-of-Change measurements across
different timescales into a single composite oscillator.  Unlike
single-period oscillators (RSI, Stochastic), KST captures momentum
at short, medium, and long timeframes simultaneously — making it
more robust to noise and regime shifts.

Reference: Martin Pring — "Martin Pring's Introduction to Technical
Analysis" (1998).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, kst


class KSTTrend(Strategy):
    """KST crossover with EMA200 trend filter.

    Entry requires KST crossover AND EMA200 alignment.

    Parameters:
        kst_roc1: Short-term ROC period (default 10).
        kst_roc2: Medium-term ROC period (default 15).
        kst_roc3: Long-term ROC period (default 20).
        kst_roc4: Very long-term ROC period (default 30).
        kst_ma1: Smoothing for ROC1 (default 10).
        kst_ma2: Smoothing for ROC2 (default 10).
        kst_ma3: Smoothing for ROC3 (default 10).
        kst_ma4: Smoothing for ROC4 (default 15).
        kst_signal: Signal line SMA period (default 9).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(roc4 + ma4, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "kst_roc1": 10,
        "kst_roc2": 15,
        "kst_roc3": 20,
        "kst_roc4": 30,
        "kst_ma1": 10,
        "kst_ma2": 10,
        "kst_ma3": 10,
        "kst_ma4": 15,
        "kst_signal": 9,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "KSTTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from KST crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        roc1 = self.params["kst_roc1"]
        roc2 = self.params["kst_roc2"]
        roc3 = self.params["kst_roc3"]
        roc4 = self.params["kst_roc4"]
        ma1 = self.params["kst_ma1"]
        ma2 = self.params["kst_ma2"]
        ma3 = self.params["kst_ma3"]
        ma4 = self.params["kst_ma4"]
        signal_period = self.params["kst_signal"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        kst_df = kst(
            close,
            roc1=roc1, roc2=roc2, roc3=roc3, roc4=roc4,
            ma1=ma1, ma2=ma2, ma3=ma3, ma4=ma4,
            signal_period=signal_period,
        )
        kst_val = kst_df["kst"]
        kst_signal = kst_df["signal"]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: KST crossover + EMA trend)
        kst_above = kst_val > kst_signal
        kst_below = kst_val < kst_signal

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = kst_above & trend_up
        short_entry = kst_below & trend_down

        # Exit: KST crosses below/above signal line
        exit_long = kst_below
        exit_short = kst_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(kst_val.iloc[i]) or pd.isna(kst_signal.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
