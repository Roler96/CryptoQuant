"""Ichimoku Cloud Breakout strategy.

Trend-following strategy using Tenkan-sen/Kijun-sen crossover confirmed
by Kumo (cloud) position. Exactly 2 entry conditions.

Entry (long):  Tenkan crosses ABOVE Kijun AND close > Senkou A AND close > Senkou B
Entry (short): Tenkan crosses BELOW Kijun AND close < Senkou A AND close < Senkou B
Exit (long):   Tenkan crosses BELOW Kijun
Exit (short):  Tenkan crosses ABOVE Kijun

The Ichimoku Kinko Hyo system's Tenkan-sen (9) / Kijun-sen (26)
crossover generates timely entry signals, while the Kumo (cloud)
provides a forward-looking support/resistance zone.

Reference: Goichi Hosoda — Ichimoku Kinko Hyo (1968); dagzk/Ichimoku_Backtest
(GitHub implementation).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ichimoku


class IchimokuCloud(Strategy):
    """Ichimoku Cloud Breakout — TK crossover + cloud trend filter.

    Entry requires both a Tenkan/Kijun cross AND price position
    relative to the Kumo (cloud). Exit on reverse TK cross.

    Parameters:
        tenkan_period: Tenkan-sen (conversion line) period (default 9)
        kijun_period: Kijun-sen (base line) period (default 26)
        senkou_b_period: Senkou Span B period (default 52)
        displacement: Cloud displacement in bars (default 26)
    """

    timeframe = "1h"
    min_bars = 100  # senkou_b_period + kijun_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "tenkan_period": 9,
        "kijun_period": 26,
        "senkou_b_period": 52,
        "displacement": 26,
    }

    @property
    def name(self) -> str:
        return "IchimokuCloud"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TK crossover + cloud filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        tenkan_period = self.params["tenkan_period"]
        kijun_period = self.params["kijun_period"]
        senkou_b_period = self.params["senkou_b_period"]
        displacement = self.params["displacement"]

        # Compute indicators
        ichi = ichimoku(
            df,
            tenkan_period=tenkan_period,
            kijun_period=kijun_period,
            senkou_b_period=senkou_b_period,
            displacement=displacement,
        )
        tenkan = ichi["tenkan"]
        kijun = ichi["kijun"]
        senkou_a = ichi["senkou_a"]
        senkou_b_vals = ichi["senkou_b"]

        # TK crossover detection (no future leakage — use shift(1) comparison)
        tk_cross_up = (tenkan > kijun) & (tenkan.shift(1) <= kijun.shift(1))
        tk_cross_down = (tenkan < kijun) & (tenkan.shift(1) >= kijun.shift(1))

        # TK position for state tracking
        tenkan_above_kijun = tenkan > kijun
        tenkan_below_kijun = tenkan < kijun

        # Cloud (Kumo) position: price relative to the cloud
        cloud_span_a_exists = senkou_a.notna()
        cloud_span_b_exists = senkou_b_vals.notna()
        cloud_exists = cloud_span_a_exists & cloud_span_b_exists

        above_cloud = (close > senkou_a) & (close > senkou_b_vals)
        below_cloud = (close < senkou_a) & (close < senkou_b_vals)

        # Entry signals (2 conditions: TK cross + cloud position)
        long_entry = tk_cross_up & above_cloud & cloud_exists
        short_entry = tk_cross_down & below_cloud & cloud_exists

        # Exit signals: TK reverse cross
        exit_long = tk_cross_down
        exit_short = tk_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(tenkan.iloc[i]) or pd.isna(kijun.iloc[i]):
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
