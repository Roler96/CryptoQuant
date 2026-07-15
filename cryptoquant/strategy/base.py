"""Strategy base class for quantitative trading strategies."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd

from cryptoquant.exceptions import StrategyError
from cryptoquant.utils import missing_ohlcv_columns


@dataclass(frozen=True)
class MarketContext:
    """One auxiliary OHLCV market required by a strategy.

    The primary DataFrame keeps the standard OHLCV column names.  Context
    columns are joined as ``<alias>_<column>``.  Separate historical and live
    symbols let the local store retain exchange-native table names while CCXT
    uses its unified symbol syntax.
    """

    alias: str
    historical_symbol: str
    live_symbol: str
    columns: tuple[str, ...]
    market_type: str = "spot"

    @property
    def output_columns(self) -> tuple[str, ...]:
        return tuple(f"{self.alias}_{column}" for column in self.columns)


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
    # True when generate_signal() returns a persistent target position
    # (1/-1/0 = long/short/flat) rather than entry pulses: the backtest
    # engine then closes the position when the signal returns to 0,
    # matching the live generate_signal_for_position() exit path.
    signal_is_position: bool = False
    # Optional auxiliary markets. Runners enrich the primary OHLCV DataFrame
    # before calling generate_signal(); orders still target the primary symbol.
    context_markets: tuple[MarketContext, ...] = ()
    # Pulse strategies can declare a frozen time exit shared by backtest/live.
    max_hold_bars: int | None = None
    execution_exchange: str | None = None
    execution_symbol: str | None = None
    execution_market_type: str | None = None
    allows_external_exits: bool = True

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

    def generate_signal_for_position(
        self, df: pd.DataFrame, position_side: str | None
    ) -> pd.Series:
        """Generate a signal with current-position context.

        Strategies with different entry and exit rules may override this hook.
        Existing strategies retain their original behavior by default.
        """
        return self.generate_signal(df)

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
        missing = missing_ohlcv_columns(df)
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
