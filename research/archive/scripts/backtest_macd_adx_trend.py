"""MACD Crossover + ADX Trend Strength Filter strategy.

Dual-condition trend-following strategy: MACD crossover generates entry
timing, ADX confirms trend strength. The ADX gate prevents entries during
weak/choppy markets where MACD crossovers produce false signals.

Entry (long):  MACD line crosses ABOVE signal line AND ADX(14) > 25
Entry (short): MACD line crosses BELOW signal line AND ADX(14) > 25
Exit (long):   MACD line crosses BELOW signal line OR ADX drops below 20
Exit (short):  MACD line crosses ABOVE signal line OR ADX drops below 20

Reference: arXiv 2511.00665 — "Technical Analysis Meets Machine Learning:
Bitcoin Evidence." The paper found MACD+ADX outperformed simple EMA
crossover on Bitcoin post-ETF data.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import adx, crossover, crossunder, macd


class MacdAdxTrend(Strategy):
    """MACD Crossover with ADX Trend Strength Confirmation.

    Parameters:
        macd_fast: MACD fast EMA period (default 12)
        macd_slow: MACD slow EMA period (default 26)
        macd_signal: MACD signal line period (default 9)
        adx_period: ADX lookback period (default 14)
        adx_threshold: ADX level above which market is trending (default 25)
        adx_exit_threshold: ADX level below which positions are closed (default 20)
    """

    timeframe = "1h"
    min_bars = 60  # macd_slow * 2 + adx_period * 2, padded
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "adx_period": 14,
        "adx_threshold": 25,
        "adx_exit_threshold": 20,
    }

    @property
    def name(self) -> str:
        return "MacdAdxTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from MACD crossover + ADX trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        macd_fast = self.params["macd_fast"]
        macd_slow = self.params["macd_slow"]
        macd_signal = self.params["macd_signal"]
        adx_period = self.params["adx_period"]
        adx_threshold = self.params["adx_threshold"]
        adx_exit_threshold = self.params["adx_exit_threshold"]

        # Compute indicators
        macd_df = macd(close, fast=macd_fast, slow=macd_slow, signal=macd_signal)
        macd_line: pd.Series = macd_df["macd"]  # type: ignore[assignment]
        macd_signal_line: pd.Series = macd_df["signal"]  # type: ignore[assignment]
        adx_df = adx(df, period=adx_period)
        adx_val = adx_df["adx"]

        # Trend strength conditions
        trending = adx_val > adx_threshold
        trend_weak = adx_val < adx_exit_threshold

        # Entry signals (gated by ADX trend filter)
        long_cross = crossover(macd_line, macd_signal_line).astype(bool)
        short_cross = crossunder(macd_line, macd_signal_line).astype(bool)

        long_entry = long_cross & trending
        short_entry = short_cross & trending

        # Exit signals: reverse MACD cross OR ADX trend weakens
        exit_long = short_cross | trend_weak
        exit_short = long_cross | trend_weak

        # Stateful signal generation
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(macd_line.iloc[i]) or pd.isna(adx_val.iloc[i]):
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
