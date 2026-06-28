"""Elder Ray Bull/Bear Power Trend Following strategy.

Trend-following strategy using Alexander Elder's Bull Power / Bear Power
indicators confirmed by an EMA trend filter. Exactly 2 entry conditions.

Elder Ray measures bar extremes (High/Low) relative to a consensus value
(EMA). When Bull Power > 0, buyers are pushing price above consensus —
enter long. When Bear Power < 0, sellers are pushing price below consensus
— enter short.

Entry (long):  Bull Power > 0 AND close > EMA(trend_period)
Entry (short): Bear Power < 0 AND close < EMA(trend_period)
Exit:          Bull Power / Bear Power crosses back to neutral

Reference: Alexander Elder — "Trading for a Living" (1993).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class ElderRayTrend(Strategy):
    """Elder Ray Bull/Bear Power with EMA trend filter.

    Bull Power = High - EMA(ema_period)
    Bear Power = Low - EMA(ema_period)

    Entry requires the power indicator to be on the right side of zero
    AND price alignment with the trend EMA.

    Parameters:
        ema_period: EMA period for consensus value (default 13)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ema_period": 13,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ElderRayTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Elder Ray Power + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]    # type: ignore[assignment]
        low: pd.Series = df["low"]      # type: ignore[assignment]

        ema_period = self.params["ema_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_consensus = ema(close, period=ema_period)
        ema_trend = ema(close, period=trend_period)

        bull_power = high - ema_consensus
        bear_power = low - ema_consensus

        # Power zero-cross detection
        bp_above = bull_power > 0
        bp_below = bull_power < 0
        bep_below = bear_power < 0
        bep_above = bear_power > 0

        prev_bp_above = bp_above.shift(1).fillna(False)
        prev_bp_below = bp_below.shift(1).fillna(False)
        prev_bep_below = bep_below.shift(1).fillna(False)
        prev_bep_above = bep_above.shift(1).fillna(False)

        # Bull Power crosses above zero → buyers take control
        bp_cross_up = bp_above & ~prev_bp_above.astype(bool)  # type: ignore[operator]
        # Bull Power crosses below zero → buyers lose control
        bp_cross_down = bp_below & ~prev_bp_below.astype(bool)  # type: ignore[operator]
        # Bear Power crosses below zero → sellers take control
        bep_cross_down = bep_below & ~prev_bep_below.astype(bool)  # type: ignore[operator]
        # Bear Power crosses above zero → sellers lose control
        bep_cross_up = bep_above & ~prev_bep_above.astype(bool)  # type: ignore[operator]

        # Trend filters (2 conditions: power signal + trend alignment)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = bp_cross_up & trend_up
        short_entry = bep_cross_down & trend_down

        exit_long = bp_cross_down | bep_cross_up
        exit_short = bep_cross_up | bp_cross_down

        # Stateful signal generation (avoid flipping in same bar)
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(ema_consensus.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
