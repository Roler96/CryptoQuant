"""Dual Moving Average Crossover strategy."""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import crossover, crossunder, ema


class MACrossover(Strategy):
    """Dual EMA crossover strategy.

    Golden cross (fast EMA crosses above slow EMA) -> long
    Death cross (fast EMA crosses below slow EMA) -> short

    Parameters:
        fast: int = 12       Fast EMA period
        slow: int = 26       Slow EMA period
        signal_type: str = "both"  Direction: "long_only" | "short_only" | "both"
    """

    timeframe = "1h"
    min_bars = 100
    DEFAULT_PARAMS = {"fast": 12, "slow": 26, "signal_type": "both"}

    @property
    def name(self) -> str:
        return "MACrossover"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        close = df["close"]

        fast_ema = ema(close, self.params["fast"])
        slow_ema = ema(close, self.params["slow"])

        signal = pd.Series(0, index=df.index, dtype=int)

        signal_type = self.params["signal_type"]

        if signal_type in ("long_only", "both"):
            signal[crossover(fast_ema, slow_ema) == 1] = 1

        if signal_type in ("short_only", "both"):
            signal[crossunder(fast_ema, slow_ema) == -1] = -1

        return signal
