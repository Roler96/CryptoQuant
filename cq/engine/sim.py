"""Simulated execution.

Fill semantics are defined here once and nowhere else:

* a decision made on bar t's close is filled at bar t+1's **open** — never
  within the bar that produced it;
* slippage always moves the price against the taker;
* stops and targets are triggered from the bar's high and low, not its close;
* when a bar touches both, the stop wins, because the tick order is unknown
  and the pessimistic reading is the honest one;
* a level the bar **gapped through** fills at the open, not at the level: a
  long stop at 9 on a bar that opened at 5 and never traded above 6 gets 5.
  Returning 9 there invents a price that did not exist in the bar at all,
  and it flatters exactly the moves that hurt most;
* a leveraged position that runs out of margin is **liquidated** rather than
  carried through negative equity to a later recovery;
* a bar that printed **zero volume is not tradeable**. OKX was down for nine
  hours on 2022-12-18 and printed flat synthetic bars for every instrument;
  filling against those invents trades that could not have happened.
"""

from __future__ import annotations

import math
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
        self, target: float, price: float, equity: float, held: float, cash: float
    ) -> float:
        """Signed quantity to trade to reach `target` weight of equity.

        Returns the difference from what is already held: there is no notion
        of "only act when the signal flips", so a target returning to zero
        closes the position by construction.

        A spot buy is additionally capped at what `cash` can actually pay for,
        fees and slippage included. Without that cap a full-weight target buys
        `equity / price` units and then pays the costs out of a balance that
        has nothing left in it, so the account finishes with negative cash —
        a margin loan on a market that does not lend.
        """
        self.spec.validate_target(target)
        if price <= 0:
            raise TradingError(f"{self.spec.inst_id}: cannot size against price {price}")
        desired = self.spec.round_quantity(target * equity / price)
        delta = desired - held
        if self.spec.market_type == "spot" and delta > 0:
            delta = min(delta, self._affordable(price, cash))
        if abs(delta) * price < self.dust_fraction * abs(equity):
            return 0.0
        return delta

    def _affordable(self, price: float, cash: float) -> float:
        """Units `cash` covers at `price`, after slippage and fee."""
        if cash <= 0:
            return 0.0
        unit_cost = self.costs.fill_price(price, Side.BUY) * (1 + self.costs.fee_bps / 10_000)
        return self.spec.round_quantity(cash / unit_cost)

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

    def liquidation_price(self, portfolio: Portfolio) -> float | None:
        """Price at which the position runs out of margin, or None.

        Solves `equity(p) == maintenance * |quantity| * p`. Spot is exempt:
        the coins are owned outright, so there is no lender to close them.
        """
        if self.spec.market_type != "swap" or portfolio.is_flat:
            return None
        quantity = portfolio.quantity
        maintenance = math.copysign(self.spec.maintenance_margin_rate, quantity)
        price = (quantity * portfolio.avg_entry - portfolio.cash) / (
            quantity * (1.0 - maintenance)
        )
        # A non-positive level for a long can never be reached, and a
        # non-positive level for a short means it is already unavoidable.
        return price if price > 0 else (None if portfolio.is_long else 0.0)

    def triggered_exit(
        self, portfolio: Portfolio, bar: Bar, stop: float | None, target: float | None
    ) -> tuple[float, str] | None:
        """The price and reason a protective exit fires within `bar`.

        Both levels touched in one bar resolves to the stop: intrabar tick
        order is unknowable, and assuming the favourable one is how a
        backtest quietly outperforms the market it claims to model.

        Liquidation is checked alongside the stop, and the two are resolved by
        price rather than by precedence — a stop above the liquidation level
        does get the position out first, which is the whole point of having
        one.
        """
        if portfolio.is_flat:
            return None

        long = portfolio.is_long
        liquidation = self.liquidation_price(portfolio)
        hit_liquidation = liquidation is not None and (
            bar.low <= liquidation if long else bar.high >= liquidation
        )
        hit_stop = stop is not None and (bar.low <= stop if long else bar.high >= stop)
        hit_target = target is not None and (
            bar.high >= target if long else bar.low <= target
        )

        if hit_liquidation and hit_stop and stop is not None and liquidation is not None:
            stop_first = stop >= liquidation if long else stop <= liquidation
            if stop_first:
                return (_reachable(stop, bar, long, adverse=True), "stop loss")
            return (_reachable(liquidation, bar, long, adverse=True), "liquidation")
        if hit_liquidation and liquidation is not None:
            return (_reachable(liquidation, bar, long, adverse=True), "liquidation")
        if hit_stop and stop is not None:
            return (_reachable(stop, bar, long, adverse=True), "stop loss")
        if hit_target and target is not None:
            return (_reachable(target, bar, long, adverse=False), "take profit")
        return None


def _reachable(level: float, bar: Bar, long: bool, adverse: bool) -> float:
    """`level`, or the open when the bar had already gapped past it.

    An order resting at a level the market opened beyond is filled at the
    open, not at the level. For an adverse level (a stop, a liquidation) that
    is worse than the level; for a favourable one (a take profit) it is
    better. Both are what actually happens, and pretending the level held is
    how a gap becomes a free option.
    """
    below = long == adverse
    return min(level, bar.open) if below else max(level, bar.open)
