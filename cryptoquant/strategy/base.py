"""Strategy base class for quantitative trading strategies."""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from cryptoquant.exceptions import StrategyError


class Strategy(ABC):
    """Quantitative strategy base class.

    All strategies must implement generate_signal() and name property.

    Signal convention:
        1  -> long entry (buy)
       -1  -> short entry (sell) -- only in swap mode, ignored in spot
        0  -> no action (hold/flat)

    Parameters injected via params dict, never hardcoded.
    """

    # Class variables: subclasses may override
    timeframe: str = "1h"
    min_bars: int = 100
    version: str = "1.0.0"

    DEFAULT_PARAMS: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None):
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.validate_params()

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name. Must be unique."""
        ...

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate trading signals from OHLCV DataFrame.

        Args:
            df: OHLCV DataFrame, columns: [open, high, low, close, volume]
                Index: DatetimeIndex (UTC)

        Returns:
            pd.Series, same length and index as df.
            Values: 1=buy, -1=sell, 0=hold

        Raises:
            StrategyError: If df has insufficient bars or missing columns.
        """
        ...

    def validate_params(self) -> bool:
        """Validate parameter legality. Subclasses may override.

        Returns:
            True if valid.

        Raises:
            StrategyError: If parameters are invalid.
        """
        return True

    def get_param(self, key: str, default: Any = None) -> Any:
        """Safely get a parameter value."""
        return self.params.get(key, default)

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """Data preprocessing hook. Subclasses may override.

        Default: check required columns + minimum bar count.
        """
        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise StrategyError(f"DataFrame missing required columns: {missing}")

        if len(df) < self.min_bars:
            raise StrategyError(
                f"Need at least {self.min_bars} bars, got {len(df)}"
            )

        return df

    def __repr__(self) -> str:
        params_str = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({params_str})"
