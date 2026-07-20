"""Simulated execution.

Fill semantics are defined here once and nowhere else:

* a decision made on bar t's close is filled at bar t+1's **open** — never
  within the bar that produced it;
* slippage always moves the price against the taker;
* stops and targets are triggered from the bar's high and low, not its close;
* when a bar touches both, the stop wins, because the tick order is unknown
  and the pessimistic reading is the honest one;
* a bar that printed **zero volume is not tradeable**. OKX was down for nine
  hours on 2022-12-18 and printed flat synthetic bars for every instrument;
  filling against those invents trades that could not have happened.
"""

from __future__ import annotations

from dataclasses import dataclass

from cq.context import Bar
from cq.core.types import CostModel, Fill, MarketSpec, Side, TradingError
from cq.engine.portfolio import Portfolio


@dataclass(frozen=True)
class Rejection:
    """Why an intended trade did not happen."""

    ts: int
    reason: str
    wanted_quantity: float


class SimBroker:
    """Turns target positions into fills against historical bars."""

    # A fully invested position drifts by floating-point noise every bar:
    # `target * equity / price` never lands exactly on what is already held.
    # Without a floor those crumbs become real orders — a buy-and-hold run
    # over five years of DOGE produced 877 "trades" instead of one, which
    # bleeds fees and makes trade count useless for bootstrap and DSR.
    DEFAULT_DUST_FRACTION = 1e-6

    def __init__(
        self,
        spec: MarketSpec,
        costs: CostModel | None = None,
        dust_fraction: float = DEFAULT_DUST_FRACTION,
    ):
        self.spec = spec
        self.costs = costs or CostModel()
        self.dust_fraction = dust_fraction
        self.rejections: list[Rejection] = []

    # ---- sizing -------------------------------------------------------

    def quantity_for_target(
        self, target: float, price: float, equity: float, held: float
    ) -> float:
        """Signed quantity to trade to reach `target` weight of equity.

        Returns the difference from what is already held: there is no notion
        of "only act when the signal flips", so a target returning to zero
        closes the position by construction.
        """
        self.spec.validate_target(target)
        if price <= 0:
            raise TradingError(f"{self.spec.inst_id}: cannot size against price {price}")
        desired = self.spec.round_quantity(target * equity / price)
        delta = desired - held
        if abs(delta) * price < self.dust_fraction * abs(equity):
            return 0.0
        return delta

    # ---- execution ----------------------------------------------------

    def execute(
        self,
        portfolio: Portfolio,
        bar: Bar,
        delta: float,
        reason: str = "",
        reference_price: float | None = None,
    ) -> Fill | None:
        """Trade `delta` against `bar`, or record why it was impossible."""
        if abs(delta) <= 0:
            return None

        if bar.volume <= 0:
            # No trade printed in this bar, so no trade could have been ours.
            self.rejections.append(
                Rejection(bar.ts, "zero-volume bar: no trade was possible", delta)
            )
            return None

        rounded = self.spec.round_quantity(delta)
        if rounded == 0:
            self.rejections.append(Rejection(bar.ts, "below lot size", delta))
            return None

        side = Side.BUY if rounded > 0 else Side.SELL
        reference = bar.open if reference_price is None else reference_price
        price = self.costs.fill_price(reference, side)
        notional = abs(rounded) * price
        if notional < self.spec.min_notional:
            self.rejections.append(Rejection(bar.ts, "below minimum notional", delta))
            return None

        fill = Fill(
            ts=bar.ts,
            inst_id=self.spec.inst_id,
            side=side,
            quantity=abs(rounded),
            price=price,
            fee=self.costs.fee(notional),
            reason=reason,
        )
        portfolio.apply(fill)
        return fill

    # ---- protective exits ---------------------------------------------

    def triggered_exit(
        self, portfolio: Portfolio, bar: Bar, stop: float | None, target: float | None
    ) -> tuple[float, str] | None:
        """The price and reason a protective exit fires within `bar`.

        Both levels touched in one bar resolves to the stop: intrabar tick
        order is unknowable, and assuming the favourable one is how a
        backtest quietly outperforms the market it claims to model.
        """
        if portfolio.is_flat:
            return None

        long = portfolio.is_long
        hit_stop = stop is not None and (bar.low <= stop if long else bar.high >= stop)
        hit_target = target is not None and (
            bar.high >= target if long else bar.low <= target
        )

        if hit_stop:
            return (stop, "stop loss") if stop is not None else None
        if hit_target:
            return (target, "take profit") if target is not None else None
        return None
