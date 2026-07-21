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

# How far off a lot boundary a quantity may sit and still count as being on
# it. Sized for accumulated binary-float error, far below any real lot.
LOT_TOLERANCE = 1e-9

# A position this close to zero is flat, not merely small. Fills never cancel
# to exactly zero once lot rounding and flips are involved — `0.3 - 0.1 - 0.2`
# leaves -2.8e-17, not 0.0 — so every flat/flip test in the engine and the
# research layer routes through `is_flat` rather than comparing to 0.0. A bare
# `== 0.0` there would read a floating-point crumb as a live reverse position
# and invent a trade that never happened.
POSITION_EPSILON = 1e-12


def is_flat(quantity: float) -> bool:
    """Whether `quantity` is a closed position rather than a live one."""
    return abs(quantity) < POSITION_EPSILON


class Side(Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class Sizing(Enum):
    """How a target weight becomes a quantity.

    These are different strategies, not implementation details, and the
    choice has to be explicit because it changes results by an order of
    magnitude.

    ON_ENTRY sizes once, when the target changes, and then holds that
    quantity — the convention a trend follower means by "1x". REBALANCE
    re-derives the quantity every bar to hold the weight constant, which
    keeps leverage fixed but trims winners on the way up and adds to losers
    on the way down. On a 5.5-year Donchian run the difference was 54 trades
    versus 2,138, and +1,747% versus +390%.
    """

    ON_ENTRY = "on_entry"
    REBALANCE = "rebalance"


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
    # Fraction of position notional the account must keep as equity before the
    # exchange closes the position. Zero is not "no liquidation": it means
    # liquidation at bankruptcy, which is the floor no venue lets a position
    # pass through. Set it to the venue's real tier rate to model the margin
    # call that actually arrives first.
    maintenance_margin_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.market_type not in ("spot", "swap"):
            raise ValueError(f"unknown market type {self.market_type!r}")
        if self.market_type == "spot" and self.max_leverage != 1.0:
            raise ValueError("spot markets cannot be leveraged")
        if self.market_type == "spot" and self.maintenance_margin_rate != 0.0:
            raise ValueError("spot positions are owned outright and cannot be liquidated")
        if not 0.0 <= self.maintenance_margin_rate < 1.0:
            raise ValueError("maintenance margin rate must be in [0, 1)")
        if self.lot_size < 0 or self.min_notional < 0:
            raise ValueError("lot size and min notional must be non-negative")

    @property
    def allows_short(self) -> bool:
        return self.market_type == "swap"

    def round_quantity(self, quantity: float) -> float:
        """Snap to the tradable lot grid, towards zero.

        Rounding towards zero rather than nearest keeps a rounded order from
        exceeding the position the caller asked for.

        The tolerance is what makes that safe rather than destructive: 0.3 is
        not representable in binary, and `0.3 / 0.1` evaluates to 2.9999...,
        so a bare floor turns an exactly tradable 0.3 into 0.2 and loses a
        third of the order. A quantity within `LOT_TOLERANCE` of a lot
        boundary is already on the grid, so it snaps to it instead.
        """
        if self.lot_size <= 0:
            return quantity
        lots = abs(quantity) / self.lot_size
        nearest = round(lots)
        if abs(lots - nearest) <= LOT_TOLERANCE * max(1.0, nearest):
            lots = float(nearest)
        else:
            lots = float(math.floor(lots))
        # Re-snapped the same way: `lots * lot_size` reintroduces the very
        # representation error this method exists to absorb (28 * 0.1 is
        # 2.8000000000000003), which then trips equality checks downstream.
        return math.copysign(_snap(lots * self.lot_size, self.lot_size), quantity)

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


def _lot_decimals(lot_size: float) -> int:
    """Decimal places `lot_size` is expressed in."""
    text = f"{lot_size:.12f}".rstrip("0")
    fraction = text.split(".")[1] if "." in text else ""
    return len(fraction)


def _snap(value: float, lot_size: float) -> float:
    """`value` cleaned of the float noise in a whole number of lots."""
    return round(value, _lot_decimals(lot_size))


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
