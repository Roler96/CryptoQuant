"""Donchian Channel Ensemble Trend-Following strategy.

Ensemble of Donchian channel breakouts with multiple lookback periods,
aggregated via majority voting into a single long/flat signal.

When price breaks above a Donchian high, that channel votes LONG.
When price breaks below a Donchian low, that channel votes FLAT.
The ensemble signal is the majority vote across all channels.

This dampens false breakouts from any single lookback while capturing
trends of varying durations.

Reference: Zarattini, Pagani & Barbon (2025), "Catching Crypto Trends:
A Tactical Approach for Bitcoin and Altcoins" (SSRN 5209907)
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import rolling_max, rolling_min


class DonchianEnsemble(Strategy):
    """Donchian Channel Ensemble — long-only trend-following via majority vote.

    Multiple Donchian channels with different lookback periods each cast
    a vote (long or flat). The ensemble signal is the majority vote,
    reducing noise from any single channel's false breakouts.

    Parameters:
        lookbacks: list[int]  Lookback periods in bars
        vote_threshold: float Fraction of channels required for long signal
    """

    timeframe = "1h"
    min_bars = 1440  # max(lookbacks) * 2 for default params
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lookbacks": [12, 24, 48, 96, 168, 336, 720],
        "vote_threshold": 0.5,
    }

    @property
    def name(self) -> str:
        return "DonchianEnsemble"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate ensemble signals from Donchian channel breakouts.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        lookbacks = self.params["lookbacks"]
        vote_threshold = self.params["vote_threshold"]
        n_channels = len(lookbacks)

        if n_channels == 0:
            return pd.Series(0, index=df.index, dtype=int)

        # Track per-channel vote: True = long, False = flat
        votes = pd.DataFrame(False, index=df.index, columns=range(n_channels))

        for i, lb in enumerate(lookbacks):
            # Donchian high/low over PREVIOUS lb bars (shifted by 1)
            # This is the standard approach: you can only break out above
            # the highest high *before* the current bar, since close <= high
            donchian_high = rolling_max(high, lb).shift(1)
            donchian_low = rolling_min(low, lb).shift(1)

            # Stateful tracking: channel is long when close > donchian_high,
            # stays long until close < donchian_low
            in_position = False

            for j in range(len(df)):
                if pd.isna(donchian_high.iloc[j]) or pd.isna(donchian_low.iloc[j]):
                    # Not enough bars yet for this lookback
                    continue

                if not in_position and close.iloc[j] > donchian_high.iloc[j]:
                    in_position = True
                elif in_position and close.iloc[j] < donchian_low.iloc[j]:
                    in_position = False

                if in_position:
                    votes.iloc[j, i] = True

        # Majority vote
        vote_count = votes.sum(axis=1)
        signal = (vote_count > n_channels * vote_threshold).astype(int)

        return signal
