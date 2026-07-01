"""HeikinAshiTrend — HA Smoothed Trend Following.

Heikin-Ashi candles filter noise reversals without adding AND gates.
HA smoothing is within-bar (not multi-bar), avoiding the extreme-smoothing
anti-pattern.

Entry (2 conditions):
    1. HA_close > HA_open (bullish candle) — price-action based, mechanical
    2. Close > EMA(trend_period) — confirms medium-term uptrend

Exit:
    HA_close < HA_open (bearish candle) — reverse signal, mechanical
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, heikin_ashi


class HeikinAshiTrend(Strategy):
    """HA smoothed trend following with EMA trend filter."""

    timeframe = "1h"
    min_bars = 60
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "trend_period": 50,
        "commission": 0.0005,
    }

    @property
    def name(self) -> str:
        return "HeikinAshiTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        # Compute Heikin-Ashi candles
        ha = heikin_ashi(df)

        # EMA trend filter
        trend_ema = ema(df["close"], self.params["trend_period"])

        # Entry: HA bullish candle + price above EMA trend
        ha_bullish = ha["ha_close"] > ha["ha_open"]
        trend_up = df["close"] > trend_ema

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[ha_bullish & trend_up] = 1

        return signal
