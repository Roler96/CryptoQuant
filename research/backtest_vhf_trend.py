"""VHF Directional Trend strategy.

Trend-following strategy using Vertical Horizontal Filter (VHF)
regime detection confirmed by SMA50 directional filter.
Exactly 2 entry conditions.

Entry (long):  VHF > vhf_entry AND close > SMA50
Entry (short): VHF > vhf_entry AND close < SMA50
Exit:          VHF drops below vhf_exit OR directional filter reverses

VHF ranges 0 to 1 — higher means the market is trending directionally.
The core insight: any directional entry works in a trending market;
the skill is knowing when you're in one.

Reference: Adam White — "The Vertical Horizontal Filter" (TASC, 1991).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, vhf


class VHFTrend(Strategy):
    """Vertical Horizontal Filter trend regime with SMA directional gate.

    Entry requires VHF above entry threshold (trending regime) AND
    price vs SMA50 directional alignment.  Exit when VHF drops below
    exit threshold (trend fading) or directional filter reverses.

    Parameters:
        vhf_period: VHF lookback period (default 20).
        vhf_entry: VHF threshold to enter (default 0.40).
        vhf_exit: VHF threshold to exit (default 0.25).
        sma_period: Directional filter period (default 50).
    """

    timeframe = "1h"
    min_bars = 220  # sma_period + vhf_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "vhf_period": 20,
        "vhf_entry": 0.40,
        "vhf_exit": 0.25,
        "sma_period": 50,
    }

    @property
    def name(self) -> str:
        return "VHFTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from VHF regime + SMA direction.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        vhf_period = self.params["vhf_period"]
        vhf_entry = self.params["vhf_entry"]
        vhf_exit = self.params["vhf_exit"]
        sma_period = self.params["sma_period"]

        # Compute indicators
        vhf_vals = vhf(df, period=vhf_period)
        sma_line = sma(close, period=sma_period)

        # Entry signals (2 conditions: VHF regime + SMA direction)
        trending = vhf_vals > vhf_entry
        above_sma = close > sma_line
        below_sma = close < sma_line

        long_entry = trending & above_sma
        short_entry = trending & below_sma

        # Exit signals: VHF drops below exit threshold OR direction flips
        trend_ending = vhf_vals < vhf_exit
        exit_long = trend_ending | below_sma
        exit_short = trend_ending | above_sma

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(vhf_vals.iloc[i]) or pd.isna(sma_line.iloc[i]):
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
