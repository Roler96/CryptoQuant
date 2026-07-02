"""Slippage models for backtesting and simulation."""
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from abc import ABC, abstractmethod

import pandas as pd


class SlippageModel(ABC):
    """Abstract base class for slippage models."""

    @abstractmethod
    def calculate(self, bar: pd.Series, side: str) -> float:
        """Return slippage as a fraction of price (e.g. 0.0005 = 5 bps).

        Args:
            bar: Single OHLCV bar with at least ``high``, ``low``, ``close``.
            side: ``"long"`` or ``"short"``.

        Returns:
            Slippage fraction to apply.
        """
        ...


class FixedSlippage(SlippageModel):
    """Constant slippage regardless of market conditions."""

    def __init__(self, slippage: float = 0.0005):
        self.slippage = slippage

    def calculate(self, bar: pd.Series, side: str) -> float:
        return self.slippage


class ATRSlippage(SlippageModel):
    """Volatility-dependent slippage scaled by ATR percentage.

    slippage = ATR_pct * multiplier, clamped to ``max_slippage``.
    """

    def __init__(
        self,
        atr_period: int = 14,
        multiplier: float = 0.5,
        max_slippage: float = 0.005,
    ):
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.max_slippage = max_slippage

    def calculate(self, bar: pd.Series, side: str) -> float:
        close = float(bar.get("close", 0))
        high = float(bar.get("high", close))
        low = float(bar.get("low", close))
        if close <= 0:
            return 0.0
        tr = max(high - low, abs(high - close), abs(low - close))
        atr_pct = tr / close
        slippage = min(atr_pct * self.multiplier, self.max_slippage)
        return slippage
