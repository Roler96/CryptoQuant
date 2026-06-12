"""Spring — failed breakdown reversal (Wyckoff Spring)."""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import new_low_bullish


class SpringReversal(Strategy):
    """Spring Reversal strategy.

    Detects false downside breakouts: price makes a new N-bar low
    but closes bullish on elevated volume, trapping sellers.

    Parameters:
        lookback: int = 30            Bars for new-low comparison
        stop_pct: float = 3.0         Stop loss (%)
        target_pct: float = 1.5       Take profit (%)
        hold_hours: int = 6           Max position hold time
        commission: float = 0.0005    Round-trip cost estimate
    """

    timeframe = "1h"
    min_bars = 100
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "lookback": 30,
        "stop_pct": 3.0,
        "target_pct": 1.5,
        "hold_hours": 6,
        "commission": 0.0005,
    }

    @property
    def name(self) -> str:
        return "SpringReversal"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        return new_low_bullish(df, lookback=self.params["lookback"])
