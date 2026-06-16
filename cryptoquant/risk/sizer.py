"""Position sizing strategies."""
from abc import ABC, abstractmethod
from enum import Enum

import numpy as np
import pandas as pd
from loguru import logger


class SizerMethod(str, Enum):
    FIXED = "fixed"
    KELLY = "kelly"
    ATR = "atr"


class PositionSizer(ABC):
    """Abstract position sizer."""

    @abstractmethod
    def calculate(self, balance: float, price: float, **kwargs) -> float:
        """Calculate position size in USDT.

        Args:
            balance: Account balance (USDT)
            price: Current price

        Returns:
            Order amount (USDT), always >= min_order and <= balance
        """
        ...


class FixedSizer(PositionSizer):
    """Fixed percentage position sizing."""

    def __init__(self, risk_pct: float = 100.0, min_order: float = 10.0):
        self.risk_pct = risk_pct
        self.min_order = min_order

    def calculate(self, balance: float, price: float, **kwargs) -> float:
        amount = balance * self.risk_pct / 100
        return max(self.min_order, amount)


class KellySizer(PositionSizer):
    """Kelly criterion position sizing.

    f* = win_rate - (1 - win_rate) / (avg_win / avg_loss)
    position = balance * f* * fraction
    """

    def __init__(
        self,
        win_rate: float = 0.5,
        avg_win_pct: float = 2.0,
        avg_loss_pct: float = 1.0,
        fraction: float = 0.5,
        min_order: float = 10.0,
        max_pct: float = 100.0,
        lookback_trades: int = 50,
        adaptive: bool = False,
    ):
        self.win_rate = win_rate
        self.avg_win_pct = avg_win_pct
        self.avg_loss_pct = avg_loss_pct
        self.fraction = fraction
        self.min_order = min_order
        self.max_pct = max_pct
        self.lookback_trades = lookback_trades
        self.adaptive = adaptive

    def calculate(self, balance: float, price: float, **kwargs) -> float:
        if self.avg_loss_pct <= 0 or self.avg_win_pct <= 0:
            kelly = 0.0
        else:
            b = self.avg_win_pct / self.avg_loss_pct
            if b <= 0:
                kelly = 0.0
            else:
                kelly = self.win_rate - (1 - self.win_rate) / b

        kelly = max(0.0, min(kelly, 1.0))
        position_pct = min(kelly * self.fraction * 100, self.max_pct)
        amount = balance * position_pct / 100
        return max(self.min_order, amount)

    def update_from_trades(self, trades: list[dict]) -> None:
        """Dynamically update Kelly params from recent trades."""
        recent = trades[-self.lookback_trades :]
        if len(recent) < 10:
            return

        wins = [t for t in recent if t.get("pnl_pct", 0) > 0]
        losses = [t for t in recent if t.get("pnl_pct", 0) <= 0]

        if not wins or not losses:
            logger.debug(
                f"Kelly update skipped: {len(wins)} wins, {len(losses)} losses"
            )
            return

        self.win_rate = len(wins) / len(recent)
        self.avg_win_pct = sum(t["pnl_pct"] for t in wins) / len(wins)
        self.avg_loss_pct = abs(sum(t["pnl_pct"] for t in losses) / len(losses))

        if (
            self.avg_win_pct <= 0
            or self.avg_loss_pct <= 0
            or not np.isfinite(self.win_rate)
        ):
            logger.warning("Kelly update produced invalid params, keeping previous values")
            return

    def feed_trades(self, trades: list[dict]) -> None:
        """Feed trade history to the sizer.

        Calls ``update_from_trades()`` when ``adaptive=True``.
        """
        if self.adaptive:
            self.update_from_trades(trades)


class ATRSizer(PositionSizer):
    """Volatility-adjusted position sizing.

    position_pct = base_risk_pct / (ATR_pct * multiplier)
    """

    def __init__(
        self,
        base_risk_pct: float = 10.0,
        atr_period: int = 14,
        multiplier: float = 1.0,
        min_order: float = 10.0,
        max_pct: float = 100.0,
    ):
        self.base_risk_pct = base_risk_pct
        self.atr_period = atr_period
        self.multiplier = multiplier
        self.min_order = min_order
        self.max_pct = max_pct

    def calculate(
        self,
        balance: float,
        price: float,
        df: pd.DataFrame | None = None,
        **kwargs,
    ) -> float:
        if df is None or len(df) < self.atr_period:
            return balance * self.base_risk_pct / 100

        try:
            from cryptoquant.strategy.signals import atr as atr_func
        except ImportError:
            logger.warning("cryptoquant.strategy.signals not available, using fallback")
            return balance * self.base_risk_pct / 100

        atr_val = atr_func(df, self.atr_period).iloc[-1]

        if pd.isna(atr_val) or atr_val == 0 or price == 0:
            return balance * self.base_risk_pct / 100

        atr_pct = atr_val / price * 100
        position_pct = min(
            self.base_risk_pct / (atr_pct * self.multiplier),
            self.max_pct,
        )
        amount = balance * position_pct / 100
        return max(self.min_order, amount)


def create_sizer(method: SizerMethod, **kwargs) -> PositionSizer:
    """Factory function."""
    sizers = {
        SizerMethod.FIXED: FixedSizer,
        SizerMethod.KELLY: KellySizer,
        SizerMethod.ATR: ATRSizer,
    }
    return sizers[method](**kwargs)
