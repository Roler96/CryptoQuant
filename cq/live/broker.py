"""Live execution against a real venue.

The counterpart to `cq.engine.sim.SimBroker`, and deliberately its mirror: it
sizes with the same `target_delta` the backtest uses, so a paper order is the
one the backtest assumed. What differs is only what a broker must differ on —
it sends the order to the exchange and reads the position and cash back as
truth, instead of applying a fill to a simulated portfolio.

Scope, stated so it cannot be mistaken for more: spot only, with market orders
for target changes and market-on-trigger OKX algos for protective exits. Swap
contracts remain separate hardening work.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cq.core.types import CostModel, Fill, MarketSpec, Side
from cq.engine.sim import Rejection
from cq.engine.sizing import target_delta
from cq.live.client import TradeError, quote_currency
from cq.live.protocols import ProtectiveOrder, TradeClient

# The same dust floor SimBroker uses, so both brokers drop the same
# floating-point crumbs to zero rather than trading them.
DEFAULT_DUST_FRACTION = 1e-6


def lot_size_of(market: dict) -> float:
    """The base-quantity increment a venue quotes an instrument in."""
    precision = (market.get("precision") or {}).get("amount")
    return float(precision) if precision else 0.0


def min_base_amount_of(market: dict) -> float:
    """Smallest order the venue accepts, in base currency."""
    minimum = (market.get("limits") or {}).get("amount", {}).get("min")
    return float(minimum) if minimum else 0.0


def spec_from_market(market: dict, inst_id: str) -> MarketSpec:
    """A spot `MarketSpec` built from a venue's own lot grid.

    Notional and amount floors are enforced by `LiveBroker` against the venue's
    base-amount minimum, so `min_notional` is left at zero here rather than
    guessed from a price that moves.
    """
    return MarketSpec(
        inst_id=inst_id,
        market_type="spot",
        lot_size=lot_size_of(market),
        min_notional=0.0,
        max_leverage=1.0,
        maintenance_margin_rate=0.0,
    )


@dataclass(frozen=True)
class Reconciliation:
    """The account as the exchange reports it, this instant."""

    held: float  # base currency owned outright
    cash: float  # free quote currency

    def equity(self, price: float) -> float:
        """Mark-to-market equity in quote terms at `price`."""
        return self.cash + self.held * price


@dataclass
class LiveBroker:
    """Turns target positions into real market orders on one spot instrument."""

    client: TradeClient
    spec: MarketSpec
    min_base_amount: float = 0.0
    costs: CostModel = field(default_factory=CostModel)
    dust_fraction: float = DEFAULT_DUST_FRACTION
    rejections: list[Rejection] = field(default_factory=list)
    active_protection: ProtectiveOrder | None = field(default=None, init=False)

    def reconcile(self) -> Reconciliation:
        """Read held base coins and free quote cash from the exchange."""
        held = self.client.base_holding(self.spec.inst_id)
        cash = self.client.free_balance(quote_currency(self.spec.inst_id))
        return Reconciliation(held=held, cash=cash)

    def is_effectively_flat(self, held: float) -> bool:
        """Whether a spot balance is too small for any venue order."""
        quantity = abs(self.spec.round_quantity(held))
        return quantity == 0 or quantity < self.min_base_amount

    def quantity_for_target(
        self, target: float, price: float, equity: float, held: float, cash: float
    ) -> float:
        """The signed quantity to reach `target`, sized exactly as the backtest."""
        return target_delta(
            self.spec, self.costs, target, price, equity, held, cash, self.dust_fraction
        )

    def execute(
        self,
        delta: float,
        ts: int,
        reason: str = "",
        client_order_id: str | None = None,
    ) -> Fill | None:
        """Send a market order for `delta`, or record why none was sent.

        `ts` stamps a rejection so it lines up with the bar that produced it,
        mirroring how `SimBroker` records the ones it declines.
        """
        rounded = self.spec.round_quantity(delta)
        if rounded == 0:
            self.rejections.append(Rejection(ts, "below lot size", delta))
            return None
        if abs(rounded) < self.min_base_amount:
            self.rejections.append(
                Rejection(ts, f"below venue minimum {self.min_base_amount}", delta)
            )
            return None
        side = Side.BUY if rounded > 0 else Side.SELL
        return self.client.market_order(
            self.spec.inst_id,
            side,
            abs(rounded),
            reason=reason,
            client_order_id=client_order_id,
        )

    # ---- protective exits --------------------------------------------

    def cancel_protection(self) -> None:
        """Cancel this session's resting exit, if any."""
        current = self.active_protection
        if current is None:
            return
        self.client.cancel_algo_order(self.spec.inst_id, current.algo_id)
        self.active_protection = None

    def adopt_protection(self, protection: ProtectiveOrder) -> None:
        """Adopt an exchange-verified order after restart reconciliation."""
        if self.active_protection is not None:
            raise TradeError(f"{self.spec.inst_id}: protection is already active")
        self.active_protection = protection

    def sync_protection(
        self,
        held: float,
        stop_loss: float | None,
        take_profit: float | None,
        client_order_id: str | None = None,
    ) -> ProtectiveOrder | None:
        """Make the resting exit exactly match the exchange-reconciled holding.

        Flat positions and intents without protective levels own no algo. An
        unchanged order is retained; a size or level change cancels the old
        algo before placing its replacement.
        """
        quantity = self.spec.round_quantity(held)
        if quantity <= 0 or (stop_loss is None and take_profit is None):
            self.cancel_protection()
            return None
        if quantity < self.min_base_amount:
            raise TradeError(
                f"{self.spec.inst_id}: held quantity {quantity} is below protective-order "
                f"minimum {self.min_base_amount}; refusing to run unprotected"
            )

        desired = (quantity, stop_loss, take_profit)
        current = self.active_protection
        if current is not None and (
            current.quantity,
            current.stop_loss,
            current.take_profit,
        ) == desired:
            return current

        self.cancel_protection()
        algo_id = self.client.place_protective_order(
            self.spec.inst_id,
            Side.SELL,
            quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            client_order_id=client_order_id,
        )
        self.active_protection = ProtectiveOrder(
            algo_id=algo_id,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            side=Side.SELL,
            client_order_id=client_order_id,
        )
        return self.active_protection
