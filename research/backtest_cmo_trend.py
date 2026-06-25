"""CMO Trend strategy.

Uses Chande Momentum Oscillator (CMO) crossover confirmed by
EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  CMO(20) crosses above SMA(CMO, 10) AND Close > EMA(200)
Entry (short): CMO(20) crosses below SMA(CMO, 10) AND Close < EMA(200)
Exit (long):   CMO crosses below signal line (momentum exhausted)
Exit (short):  CMO crosses above signal line

CMO uses raw sum of up/down moves over the lookback period rather than
smoothed average gains/losses (RSI). This makes it faster and more
responsive to regime changes. The normalized 0-100 scale means it
works across timeframes without parameter tuning — similar advantage
to %B and Stochastic. Crossover entry generates more signals than
threshold-gated entry (e.g., %B at 0.8).

Reference: Tushar Chande — "The New Technical Trader" (1994).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import cmo, ema, sma


class CMOTrend(Strategy):
    """CMO crossover with EMA200 trend filter.

    Entry requires CMO zero-line crossover AND EMA200 alignment.

    Parameters:
        cmo_period: CMO lookback period (default 20)
        signal_period: SMA period for CMO signal line (default 10)
        trend_period: Period for trend filter EMA (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "cmo_period": 20,
        "signal_period": 10,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "CMOTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from CMO crossover + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        cmo_period = self.params["cmo_period"]
        signal_period = self.params["signal_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        cmo_val = cmo(close, period=cmo_period)
        cmo_signal = sma(cmo_val, period=signal_period)

        # Entry signals: 2 conditions (CMO crossover + trend filter)
        # Long: CMO crosses above signal line AND close > EMA200
        long_entry = (cmo_val > cmo_signal) & (cmo_val.shift(1) <= cmo_signal.shift(1)) & (close > ema_trend)
        # Short: CMO crosses below signal line AND close < EMA200
        short_entry = (cmo_val < cmo_signal) & (cmo_val.shift(1) >= cmo_signal.shift(1)) & (close < ema_trend)

        # Exit signals: reverse crossover
        exit_long = cmo_val < cmo_signal
        exit_short = cmo_val > cmo_signal

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(cmo_val.iloc[i]):
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
