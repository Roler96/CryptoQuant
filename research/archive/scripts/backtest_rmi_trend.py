"""RMI Trend strategy.

Trend-following strategy using Relative Momentum Index (RMI) crossover
with its signal line, confirmed by EMA200 trend direction filter.
Exactly 2 entry conditions.

RMI improves on RSI by measuring momentum (N-bar price change) instead
of single-bar price changes.  The additional smoothing produces clearer
turning points and reduces false signals in choppy markets.  The signal
line EMA further smooths the oscillator for crossover-style entries.

Entry (long):  RMI crosses above Signal AND close > EMA200
Entry (short): RMI crosses below Signal AND close < EMA200
Exit:          RMI crosses back below/above Signal (reverse signal)

Reference: Roger Altman — "Relative Momentum Index" (1993).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, rmi, crossover, crossunder


class RmiTrend(Strategy):
    """RMI crossover with signal line and EMA200 trend filter.

    Uses RMI (Relative Momentum Index) — a momentum-based variation of
    RSI that measures price change over N bars.  RMI/Signal crossover
    is the primary trigger; EMA200 provides directional confirmation.
    2 conditions.

    Parameters:
        momentum_period: Bars for momentum calculation (default 5).
        rmi_period: Wilder's EMA period for smoothing (default 14).
        signal_period: Signal line EMA period (default 9).
        trend_period: EMA period for trend direction filter (default 200).
    """

    timeframe = "1h"
    min_bars = 220  # trend_period + rmi warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "momentum_period": 5,
        "rmi_period": 14,
        "signal_period": 9,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "RmiTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from RMI crossover + EMA200 direction.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        momentum_period = self.params["momentum_period"]
        rmi_period = self.params["rmi_period"]
        signal_period = self.params["signal_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        rmi_df = rmi(
            df,
            momentum_period=momentum_period,
            rmi_period=rmi_period,
            signal_period=signal_period,
        )
        rmi_line: pd.Series = rmi_df["rmi"]  # type: ignore[assignment]
        signal_line: pd.Series = rmi_df["signal"]  # type: ignore[assignment]
        trend_line = ema(close, period=trend_period)

        # Entry signals (2 conditions: RMI/Signal cross + trend direction)
        long_entry = (
            crossover(rmi_line, signal_line).astype(bool)
            & (close > trend_line)
        )
        short_entry = (
            crossunder(rmi_line, signal_line).astype(bool)
            & (close < trend_line)
        )

        # Exit signals: reverse crossover
        exit_long = crossunder(rmi_line, signal_line).astype(bool)
        exit_short = crossover(rmi_line, signal_line).astype(bool)

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(rmi_line.iloc[i])
                or pd.isna(signal_line.iloc[i])
                or pd.isna(trend_line.iloc[i])
            ):
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
