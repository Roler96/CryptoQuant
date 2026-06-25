"""CLV ATR Momentum strategy.

Combines Close Location Value (CLV) momentum with ATR-based volatility
expansion filter. CLV measures where the close sits within the bar range
(-1 = at low, +1 = at high). A smoothed CLV crossing a threshold signals
directional momentum, and ATR above its Nth percentile confirms genuine
volatility expansion (not noise).

Entry (long):  CLV SMA crosses above threshold AND ATR > ATR percentile
Entry (short): CLV SMA crosses below -threshold AND ATR > ATR percentile
Exit (long):   CLV SMA crosses below 0 (momentum died)
Exit (short):  CLV SMA crosses above 0 (momentum died)

The ATR percentile filter eliminates ~40-50% of CLV noise crossings.
This is a pure momentum strategy — no trend filter, no regime switching.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, crossover, crossunder


class ClvAtrMomentum(Strategy):
    """CLV Momentum with ATR Expansion Filter.

    Parameters:
        clv_period: SMA smoothing period for CLV (default 10)
        clv_threshold: CLV cross threshold for entry (default 0.3)
        atr_period: ATR lookback period (default 14)
        atr_percentile: ATR must exceed Nth percentile of recent window (default 60)
        atr_percentile_window: Window for percentile calculation (default 100)
    """

    timeframe = "1h"
    min_bars = 120  # max(clv_period, atr_period, atr_percentile_window) * 1.2
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "clv_period": 10,
        "clv_threshold": 0.3,
        "atr_period": 14,
        "atr_percentile": 60,
        "atr_percentile_window": 100,
    }

    @property
    def name(self) -> str:
        return "ClvAtrMomentum"

    def _clv(self, df: pd.DataFrame) -> pd.Series:
        """Compute Close Location Value per bar.

        CLV = (2*close - high - low) / (high - low)
        Range [-1, +1]: +1 = close at high, -1 = close at low.
        """
        close = df["close"]
        high = df["high"]
        low = df["low"]
        bar_range = (high - low).clip(lower=1e-10)
        return (2 * close - high - low) / bar_range

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from CLV momentum with ATR filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)

        clv_period = self.params["clv_period"]
        clv_threshold = self.params["clv_threshold"]
        atr_period = self.params["atr_period"]
        atr_percentile = self.params["atr_percentile"]
        atr_percentile_window = self.params["atr_percentile_window"]

        close: pd.Series = df["close"]  # type: ignore[assignment]

        # CLV and smoothed CLV
        clv_raw = self._clv(df)
        clv_sma = clv_raw.rolling(clv_period).mean()

        # CLV cross signals (shifted: no look-ahead)
        long_cross = crossover(clv_sma, pd.Series(clv_threshold, index=df.index))
        short_cross = crossunder(clv_sma, pd.Series(-clv_threshold, index=df.index))

        long_exit_cross = crossunder(clv_sma, pd.Series(0.0, index=df.index))
        short_exit_cross = crossover(clv_sma, pd.Series(0.0, index=df.index))

        # ATR percentile filter: only enter when volatility is above Nth percentile
        atr_val = atr(df, period=atr_period)
        atr_rank = atr_val.rolling(atr_percentile_window).apply(
            lambda x: np.mean(x <= x.iloc[-1]) * 100, raw=False
        )
        vol_ok = atr_rank > atr_percentile

        # Entry signals (2 conditions: cross + ATR expansion)
        long_entry = (long_cross == 1) & vol_ok
        short_entry = (short_cross == -1) & vol_ok

        # Exit signals
        exit_long = long_exit_cross == -1
        exit_short = short_exit_cross == 1

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(clv_sma.iloc[i]) or pd.isna(atr_val.iloc[i]):
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
