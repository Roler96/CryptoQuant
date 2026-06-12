"""Wick Inversion — buy when sellers try hard and fail."""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import pct_change_rolling, wick_imbalance


class WickInversion(Strategy):
    """Wick Inversion strategy.

    Detects seller exhaustion via upper wick pressure + volume,
    enters long when imbalance exceeds threshold and price is not
    in free-fall.

    Parameters:
        imbalance_window: int = 6     Rolling sum window for wick pressure
        imbalance_threshold: float = 0.25  Min seller/buyer imbalance
        price_lookback: int = 6       Price change calculation window (hours)
        price_floor: float = -0.5     Min 6h price change (%) to allow entry
        stop_pct: float = 3.0         Stop loss (%)
        target_pct: float = 1.5       Take profit (%)
        hold_hours: int = 12          Max position hold time
        commission: float = 0.0005    Round-trip cost estimate
    """

    timeframe = "1h"
    min_bars = 100
    version = "4.3.0"

    DEFAULT_PARAMS = {
        "imbalance_window": 6,
        "imbalance_threshold": 0.25,
        "price_lookback": 6,
        "price_floor": -0.5,
        "stop_pct": 3.0,
        "target_pct": 1.5,
        "hold_hours": 12,
        "commission": 0.0005,
    }

    @property
    def name(self) -> str:
        return "WickInversion"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        imb = wick_imbalance(df, window=self.params["imbalance_window"])
        price_chg = pct_change_rolling(
            df["close"], self.params["price_lookback"]
        )

        signal = (imb > self.params["imbalance_threshold"]) & (
            price_chg > self.params["price_floor"]
        )

        return signal.astype(int)
