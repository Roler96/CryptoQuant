"""Laguerre RSI Expansion Trend strategy.

Trend-following strategy using Laguerre RSI(14) midline crossover as the
primary entry trigger, confirmed by ATR expansion filter.  Exactly
2 entry conditions — matches the proven 2-condition template.

The Laguerre RSI (Ehlers, 2002) reduces lag vs standard RSI via a
4-pole gamma filter, producing earlier signals during trend transitions.

The ATR expansion filter (bar range > ATR percentile) is the most-proven
universal confirmation filter.

Entry (long):  LaguerreRSI(14, γ=0.5) > 50 AND bar_range > ATR(14) pctile
Entry (short): LaguerreRSI(14, γ=0.5) < 50 AND bar_range > ATR(14) pctile
Exit (long):   LaguerreRSI crosses below 50 (reverse signal)
Exit (short):  LaguerreRSI crosses above 50 (reverse signal)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, laguerre_rsi


class LaguerreRSIExpansion(Strategy):
    """Laguerre RSI midline crossover with ATR expansion confirmation.

    Parameters:
        lrsi_period: Laguerre RSI EMA period (default 14).
        lrsi_gamma: Laguerre pole location, 0<γ<1 (default 0.5).
        atr_period: ATR lookback (default 14).
        atr_percentile_window: Rolling percentile window for ATR (default 50).
        atr_percentile: Percentile threshold for expansion (default 80).
        lrsi_long_entry: LaguerreRSI threshold for long (default 50).
        lrsi_short_entry: LaguerreRSI threshold for short (default 50).
    """

    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lrsi_period": 14,
        "lrsi_gamma": 0.5,
        "atr_period": 14,
        "atr_percentile_window": 50,
        "atr_percentile": 80,
        "lrsi_long_entry": 50,
        "lrsi_short_entry": 50,
    }

    @property
    def name(self) -> str:
        return "LaguerreRSIExpansion"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Laguerre RSI crossover + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        lrsi_period = self.params["lrsi_period"]
        lrsi_gamma = self.params["lrsi_gamma"]
        atr_period = self.params["atr_period"]
        atr_window = self.params["atr_percentile_window"]
        atr_pct = self.params["atr_percentile"]
        lrsi_long = self.params["lrsi_long_entry"]
        lrsi_short = self.params["lrsi_short_entry"]

        # Compute indicators
        lrsi_val = laguerre_rsi(close, period=lrsi_period, gamma=lrsi_gamma)
        atr_val = atr(df, period=atr_period)
        bar_range = df["high"] - df["low"]

        # ATR expansion: bar_range > percentile of recent ATR
        atr_pctile = atr_val.rolling(atr_window, min_periods=atr_window).apply(
            lambda x: np.percentile(x, atr_pct), raw=True
        )
        expansion = bar_range > atr_pctile

        # Entry conditions (2 conditions)
        lrsi_above = lrsi_val > lrsi_long
        lrsi_below = lrsi_val < lrsi_short

        long_entry = lrsi_above & expansion
        short_entry = lrsi_below & expansion

        # Exit: LaguerreRSI crosses back across threshold
        exit_long = lrsi_below
        exit_short = lrsi_above

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(lrsi_val.iloc[i])
                or pd.isna(atr_val.iloc[i])
                or pd.isna(atr_pctile.iloc[i])
            ):
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
