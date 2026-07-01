"""VWAPTrend — Anchored VWAP Momentum.

VWAP (Volume-Weighted Average Price) is the institutional standard for
order execution. In crypto it's underutilized. Price above VWAP signals
bullish momentum (buyers in control); below VWAP signals bearish.

VWAP naturally multiplies signal strength by volume without gating entry
— follows the proven Force Index / MFI pattern.

Entry (2 conditions):
    1. Close > VWAP(vwap_period) — volume-weighted bullish pressure
    2. Volume > SMA(volume, vol_period) — confirms genuine interest

Exit:
    Close < VWAP(vwap_period) — reverse signal
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import vwap


class VWAPTrend(Strategy):
    """Anchored VWAP momentum with volume confirmation."""

    timeframe = "1h"
    min_bars = 50
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "vwap_period": 20,
        "vol_period": 20,
        "commission": 0.0005,
    }

    @property
    def name(self) -> str:
        return "VWAPTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        # Rolling VWAP
        vwap_line = vwap(df, period=self.params["vwap_period"])

        # Volume confirmation: volume > SMA(volume)
        vol_sma = df["volume"].rolling(self.params["vol_period"]).mean()

        # Entry: close > VWAP + volume confirmation
        above_vwap = df["close"] > vwap_line
        volume_ok = df["volume"] > vol_sma

        signal = pd.Series(0, index=df.index, dtype=int)
        signal[above_vwap & volume_ok] = 1

        return signal
