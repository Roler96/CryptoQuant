"""BB Upper Breakout — momentum continuation strategy.

Detects breakouts above wide Bollinger Bands, signalling strong
momentum that tends to continue for several bars.

Signal:
    close > BB(period, std).upper AND close > SMA(200)

Parameters:
    bb_period: int = 50         Bollinger Band period
    bb_std: float = 2.5         Bollinger Band standard deviations
    sma_period: int = 200       SMA trend filter period
    stop_pct: float = 1.2       Stop loss (%)
    target_pct: float = 4.0     Take profit (%)
    hold_hours: int = 10        Max position hold time
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import sma, bollinger_bands


class BBUpperBreakout(Strategy):
    """BB Upper Breakout — momentum continuation."""

    timeframe = "1h"
    min_bars = 250
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 50,
        "bb_std": 2.5,
        "sma_period": 200,
        "stop_pct": 1.2,
        "target_pct": 4.0,
        "hold_hours": 10,
        "commission": 0.0005,
    }

    @property
    def name(self) -> str:
        return "BBUpperBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        bb = bollinger_bands(
            df, period=self.params["bb_period"], std=self.params["bb_std"]
        )
        sma200 = sma(df["close"], self.params["sma_period"])

        signal = (df["close"] > bb["upper"]) & (df["close"] > sma200)
        return signal.astype(int)
