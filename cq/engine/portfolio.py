"""Position and cash accounting.

Profit is derived from the fill ledger — entry cost, exit proceeds, fees,
funding — and never from the change in a balance. The previous system read
PnL off free-balance deltas and booked sale proceeds as profit, so the same
losing trade was recorded as -10% and +89.91 USDT at once.

Spot holdings are owned by the strategy. Selling more than the strategy
bought raises rather than sweeping whatever else is in the account: that
defect could liquidate coins a human or another strategy put there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from cq.core.types import Fill, MarketSpec, Side, TradingError

QUANTITY_EPSILON = 1e-12
# Cash comparisons carry the rounding of a price times a quantity, so they are
# made with a relative tolerance rather than exactly.
CASH_EPSILON = 1e-9


@dataclass
class FundingPayment:
    ts: int
    rate: float
    mark_price: float
    amount: float  # positive when the position paid


@dataclass
class Portfolio:
    """One strategy's cash, position and realised results for one market."""

    spec: MarketSpec
    initial_cash: float
    cash: float = field(init=False)
    quantity: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    funding_paid: float = 0.0
    fills: list[Fill] = field(default_factory=list)
    funding_payments: list[FundingPayment] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial cash must be positive")
        self.cash = self.initial_cash

    # ---- state --------------------------------------------------------

    @property
    def is_flat(self) -> bool:
        return abs(self.quantity) < QUANTITY_EPSILON

    @property
    def is_long(self) -> bool:
        return self.quantity > QUANTITY_EPSILON

    @property
    def is_short(self) -> bool:
        return self.quantity < -QUANTITY_EPSILON

    def unrealized_pnl(self, mark_price: float) -> float:
        if self.is_flat:
            return 0.0
        return self.quantity * (mark_price - self.avg_entry)

    def position_value(self, mark_price: float) -> float:
        """What the position is worth on the books.

        Spot holdings are an asset carried at market value. A swap position
        is collateralised by cash, so only its mark-to-market shows up.
        """
        if self.spec.market_type == "spot":
            return self.quantity * mark_price
        return self.unrealized_pnl(mark_price)

    def equity(self, mark_price: float) -> float:
        return self.cash + self.position_value(mark_price)

    @property
    def net_pnl(self) -> float:
        """Realised result after every cost. Never a balance difference."""
        return self.realized_pnl - self.fees_paid - self.funding_paid

    # ---- mutation -----------------------------------------------------

    def apply(self, fill: Fill) -> None:
        """Book a fill: costs, position, cash and realised PnL."""
        if fill.quantity <= 0:
            raise ValueError(f"fill quantity must be positive, got {fill.quantity}")
        if fill.price <= 0:
            raise ValueError(f"fill price must be positive, got {fill.price}")

        delta = fill.signed_quantity
        self._check_ownership(fill, delta)

        # Realise against the cost basis, not against the last price.
        closing = self._closing_quantity(delta)
        realized_now = closing * (fill.price - self.avg_entry) if closing else 0.0
        self.realized_pnl += realized_now

        new_quantity = self.quantity + delta
        if abs(new_quantity) < QUANTITY_EPSILON:
            new_quantity = 0.0
            self.avg_entry = 0.0
        elif self.is_flat or _same_sign(self.quantity, new_quantity):
            if _same_sign(delta, new_quantity) and abs(new_quantity) > abs(self.quantity):
                # Adding to the position moves the cost basis.
                added = abs(delta)
                held = abs(self.quantity)
                self.avg_entry = (self.avg_entry * held + fill.price * added) / (held + added)
            # Reducing leaves the basis alone.
        else:
            # Flipped through zero: the remainder is a fresh position.
            self.avg_entry = fill.price

        self.quantity = new_quantity
        self.fees_paid += fill.fee
        if self.spec.market_type == "spot":
            # Cash buys the asset and is returned when it is sold.
            self.cash += -fill.signed_quantity * fill.price - fill.fee
        else:
            # A swap position is collateralised, not bought: only realised
            # results and costs move cash.
            self.cash += realized_now - fill.fee
        self.fills.append(fill)

    def apply_funding(self, ts: int, rate: float, mark_price: float) -> FundingPayment:
        """Settle one funding period against the open position."""
        if self.spec.market_type != "swap":
            raise TradingError(f"{self.spec.inst_id} is spot and has no funding")
        amount = self.quantity * mark_price * rate
        self.cash -= amount
        self.funding_paid += amount
        payment = FundingPayment(ts=ts, rate=rate, mark_price=mark_price, amount=amount)
        self.funding_payments.append(payment)
        return payment

    # ---- internals ----------------------------------------------------

    def _check_ownership(self, fill: Fill, delta: float) -> None:
        if self.spec.market_type != "spot":
            return
        if fill.side is Side.SELL and fill.quantity > self.quantity + QUANTITY_EPSILON:
            raise TradingError(
                f"{self.spec.inst_id}: selling {fill.quantity} but this strategy only "
                f"holds {self.quantity}; the rest of the account is not ours to sell"
            )
        if self.quantity + delta < -QUANTITY_EPSILON:
            raise TradingError(f"{self.spec.inst_id} is spot and cannot go short")
        if fill.side is Side.BUY:
            # The mirror of the rule above. Spot has no lender: cash that is
            # not there cannot buy anything, and a balance allowed to go
            # negative is an unfunded margin loan at zero interest.
            cost = fill.notional + fill.fee
            if cost > self.cash + CASH_EPSILON * max(1.0, abs(self.cash)):
                raise TradingError(
                    f"{self.spec.inst_id}: buying {fill.quantity} at {fill.price} costs "
                    f"{cost:.8f} including fees but only {self.cash:.8f} cash is held; "
                    f"spot cannot borrow"
                )

    def _closing_quantity(self, delta: float) -> float:
        """Signed quantity being closed by `delta`, in position terms."""
        if self.is_flat or _same_sign(self.quantity, delta):
            return 0.0
        return math.copysign(min(abs(delta), abs(self.quantity)), self.quantity)


def _same_sign(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)
