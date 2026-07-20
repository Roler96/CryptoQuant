"""Value types shared by the engine.

Spot and swap differ in what they permit, not in which code path they take:
the differences live in `MarketSpec` as data, so the engine has one
implementation and no `if market_type ==` scattered through it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Literal

MarketType = Literal["spot", "swap"]

# 10 bps exchange fee + 5 bps slippage per side, the cost basis every prior
# study in this project used. Kept as the default so results stay comparable.
DEFAULT_FEE_BPS = 10.0
DEFAULT_SLIPPAGE_BPS = 5.0


class Side(Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class TradingError(Exception):
    """A rule of the market or the account was violated."""


@dataclass(frozen=True)
class MarketSpec:
    """What one instrument permits.

    `allows_short` is not a free-standing flag: it follows from the market
    type, so a spot instrument cannot be configured into allowing shorts by
    accident.
    """

    inst_id: str
    market_type: MarketType = "spot"
    lot_size: float = 0.0
    min_notional: float = 0.0
    max_leverage: float = 1.0

    def __post_init__(self) -> None:
        if self.market_type not in ("spot", "swap"):
            raise ValueError(f"unknown market type {self.market_type!r}")
        if self.market_type == "spot" and self.max_leverage != 1.0:
            raise ValueError("spot markets cannot be leveraged")
        if self.lot_size < 0 or self.min_notional < 0:
            raise ValueError("lot size and min notional must be non-negative")

    @property
    def allows_short(self) -> bool:
        return self.market_type == "swap"

    def round_quantity(self, quantity: float) -> float:
        """Snap to the tradable lot grid, towards zero.

        Rounding towards zero rather than nearest keeps a rounded order from
        exceeding the position the caller asked for.
        """
        if self.lot_size <= 0:
            return quantity
        lots = math.floor(abs(quantity) / self.lot_size)
        return math.copysign(lots * self.lot_size, quantity)

    def validate_target(self, weight: float) -> None:
        """Reject a target this market cannot hold.

        Silently clamping a short to flat on spot would let a long/short
        strategy backtest as a long-only one without anybody noticing.
        """
        if weight < 0 and not self.allows_short:
            raise TradingError(
                f"{self.inst_id} is spot and cannot hold a short target ({weight}); "
                f"clamping it to zero would silently change the strategy"
            )
        if abs(weight) > self.max_leverage:
            raise TradingError(
                f"{self.inst_id}: target {weight} exceeds max leverage {self.max_leverage}"
            )


@dataclass(frozen=True)
class Intent:
    """What a strategy wants to hold after this bar.

    A target, never a pulse. The engine trades the difference from the current
    position, so "signal returned to zero" closes the position by construction
    — there is no separate exit rule to forget.
    """

    target: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not math.isfinite(self.target):
            raise ValueError(f"target must be finite, got {self.target}")
        for name, level in (("stop_loss", self.stop_loss), ("take_profit", self.take_profit)):
            if level is not None and level <= 0:
                raise ValueError(f"{name} must be a positive price, got {level}")


FLAT = Intent(target=0.0)


@dataclass(frozen=True)
class Fill:
    """An executed trade, with its costs already separated out."""

    ts: int
    inst_id: str
    side: Side
    quantity: float
    price: float
    fee: float
    reason: str = ""

    @property
    def notional(self) -> float:
        return self.quantity * self.price

    @property
    def signed_quantity(self) -> float:
        return self.quantity * self.side.sign


@dataclass(frozen=True)
class CostModel:
    """Execution costs, charged per side."""

    fee_bps: float = DEFAULT_FEE_BPS
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS

    def __post_init__(self) -> None:
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("costs cannot be negative")

    def fill_price(self, reference: float, side: Side) -> float:
        """Reference price moved against the taker."""
        return reference * (1 + side.sign * self.slippage_bps / 10_000)

    def fee(self, notional: float) -> float:
        return abs(notional) * self.fee_bps / 10_000
