"""CMO Trend strategy.

Trend-following strategy using Chande Momentum Oscillator (CMO) zero-cross
as the primary entry trigger, confirmed by EMA200 trend filter. Exactly
2 conditions — matches the proven 2-condition template.

CMO uses raw momentum sums (not Wilder smoothing like RSI), making it
more responsive to sustained directional moves while the 20-bar rolling
sum provides natural noise filtering.

Entry (long):  CMO(20) crosses above 0 AND close > EMA(200)
Entry (short): CMO(20) crosses below 0 AND close < EMA(200)
Exit (long):   CMO crosses below 0 (zero-cross reversal)
Exit (short):  CMO crosses above 0 (zero-cross reversal)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import cmo, ema


class CMOTrend(Strategy):
    """CMO zero-cross trend with EMA200 directional filter.

    Parameters:
        cmo_period: CMO lookback period (default 20).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 250  # max(cmo_period=20, trend_period=200) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "cmo_period": 20,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "CMOTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from CMO zero-cross + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        cmo_period = self.params["cmo_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        cmo_val = cmo(close, period=cmo_period)
        trend_ema = ema(close, period=trend_period)

        # Entry conditions (2 conditions: CMO cross + trend filter)
        cmo_above_zero = cmo_val > 0
        cmo_below_zero = cmo_val < 0
        above_trend = close > trend_ema
        below_trend = close < trend_ema

        long_entry = cmo_above_zero & above_trend
        short_entry = cmo_below_zero & below_trend

        # Exit: CMO crosses back to zero
        exit_long = cmo_below_zero
        exit_short = cmo_above_zero

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(cmo_val.iloc[i]) or pd.isna(trend_ema.iloc[i]):
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
