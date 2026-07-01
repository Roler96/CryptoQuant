"""OBV Trend Following strategy.

Trend-following strategy using On-Balance Volume (OBV) crossover
confirmed by EMA200 trend filter. Exactly 2 entry conditions.

OBV is a cumulative volume-flow indicator — it measures whether
volume is flowing into or out of the asset. Unlike price oscillators,
OBV directly tracks the "smart money" flow that volume theory posits
precedes price movement.

Entry (long):  OBV crosses above its SMA AND close > EMA200
Entry (short): OBV crosses below its SMA AND close < EMA200
Exit (long):   OBV crosses below its SMA
Exit (short):  OBV crosses above its SMA

Reference: Joseph Granville — "Granville's New Key to Stock
Market Profits" (1963).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, obv_sma


class OBVTrend(Strategy):
    """OBV crossover with EMA200 trend filter.

    Entry requires OBV crossover AND EMA200 alignment.
    Two conditions total.

    Parameters:
        obv_sma_period: SMA period for OBV signal line (default 20).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(obv_sma_period, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "obv_sma_period": 20,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "OBVTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from OBV crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        obv_period = self.params["obv_sma_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        obv_df = obv_sma(df, period=obv_period)
        obv_val = obv_df["obv"]
        obv_signal = obv_df["signal"]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: OBV crossover + EMA trend)
        obv_above = obv_val > obv_signal
        obv_below = obv_val < obv_signal

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = obv_above & trend_up
        short_entry = obv_below & trend_down

        # Exit: OBV crosses back
        exit_long = obv_below
        exit_short = obv_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(obv_val.iloc[i]) or pd.isna(obv_signal.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
