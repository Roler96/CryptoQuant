"""Turning a target weight into a signed quantity — the one implementation.

Both the simulated broker and the live broker call this, so a paper or live
order is sized by exactly the arithmetic the backtest was sized by. If sizing
lived twice, the two copies would drift and a backtest could quietly assume a
position the live account could never afford.
"""

from __future__ import annotations

from cq.core.types import CostModel, MarketSpec, Side, TradingError


def target_delta(
    spec: MarketSpec,
    costs: CostModel,
    target: float,
    price: float,
    equity: float,
    held: float,
    cash: float,
    dust_fraction: float,
) -> float:
    """Signed quantity to trade to reach `target` weight of equity.

    Returns the difference from what is already held, so a target of zero closes
    the position by construction — there is no separate "only act on a flip".

    A spot buy is capped at what `cash` can actually pay for, fees and slippage
    included: without that cap a full-weight target buys `equity / price` units
    and then owes the costs out of an empty balance, finishing on negative cash
    — a margin loan on a market that does not lend.

    A delta whose notional is below `dust_fraction` of equity is dropped to
    zero, so floating-point drift in `target * equity / price` never becomes a
    stream of fee-bleeding micro-orders.
    """
    spec.validate_target(target)
    if price <= 0:
        raise TradingError(f"{spec.inst_id}: cannot size against price {price}")
    desired = spec.round_quantity(target * equity / price)
    delta = desired - held
    if spec.market_type == "spot" and delta > 0:
        delta = min(delta, _affordable(spec, costs, price, cash))
    if abs(delta) * price < dust_fraction * abs(equity):
        return 0.0
    return delta


def _affordable(spec: MarketSpec, costs: CostModel, price: float, cash: float) -> float:
    """Units `cash` covers at `price`, after slippage and fee."""
    if cash <= 0:
        return 0.0
    unit_cost = costs.fill_price(price, Side.BUY) * (1 + costs.fee_bps / 10_000)
    return spec.round_quantity(cash / unit_cost)
