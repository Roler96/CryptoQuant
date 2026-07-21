"""Live execution against a real venue.

The counterpart to `cq.engine.sim.SimBroker`, and deliberately its mirror: it
sizes with the same `target_delta` the backtest uses, so a paper order is the
one the backtest assumed. What differs is only what a broker must differ on —
it sends the order to the exchange and reads the position and cash back as
truth, instead of applying a fill to a simulated portfolio.

Scope, stated so it cannot be mistaken for more: spot and linear quote-settled
swaps, with market orders for target changes and market-on-trigger OKX algos
for protective exits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cq.core.types import CostModel, Fill, MarketSpec, Side
from cq.engine.sim import Rejection
from cq.engine.sizing import target_delta
from cq.live.client import TradeError, quote_currency
from cq.live.protocols import AccountEvent, ProtectiveOrder, TradeClient

# The same dust floor SimBroker uses, so both brokers drop the same
# floating-point crumbs to zero rather than trading them.
DEFAULT_DUST_FRACTION = 1e-6


def lot_size_of(market: dict) -> float:
    """The base-quantity increment represented by one venue amount step."""
    precision = (market.get("precision") or {}).get("amount")
    raw_lot = float(precision) if precision else 0.0
    return raw_lot * contract_size_of(market)


def min_base_amount_of(market: dict) -> float:
    """Smallest order the venue accepts, in base currency."""
    minimum = (market.get("limits") or {}).get("amount", {}).get("min")
    raw_minimum = float(minimum) if minimum else 0.0
    return raw_minimum * contract_size_of(market)


def contract_size_of(market: dict) -> float:
    """Base-currency value of one contract, or one for spot."""
    is_contract = bool(market.get("contract")) or market.get("type") == "swap"
    if not is_contract:
        return 1.0
    if not market.get("linear"):
        raise ValueError("only linear quote-settled swap contracts are supported")
    value = market.get("contractSize")
    if value is None or float(value) <= 0:
        raise ValueError("swap market has no positive contractSize")
    return float(value)


def spec_from_market(
    market: dict,
    inst_id: str,
    max_leverage: float | None = None,
) -> MarketSpec:
    """A spot or linear-swap `MarketSpec` built from venue metadata.

    Notional and amount floors are enforced by `LiveBroker` against the venue's
    base-amount minimum, so `min_notional` is left at zero here rather than
    guessed from a price that moves.
    """
    is_swap = bool(market.get("swap")) or market.get("type") == "swap"
    if is_swap != inst_id.endswith("-SWAP"):
        raise ValueError(f"market type does not match instrument id {inst_id!r}")
    if is_swap and market.get("settle") != quote_currency(inst_id):
        raise ValueError("only quote-settled linear swaps are supported")
    contract_size = contract_size_of(market)
    leverage = max_leverage if max_leverage is not None else 1.0
    return MarketSpec(
        inst_id=inst_id,
        market_type="swap" if is_swap else "spot",
        lot_size=lot_size_of(market),
        min_notional=0.0,
        max_leverage=leverage,
        maintenance_margin_rate=0.0,
        contract_size=contract_size,
    )


@dataclass(frozen=True)
class Reconciliation:
    """The account as the exchange reports it, this instant."""

    held: float  # signed base-equivalent position
    cash: float  # spot free quote or swap settlement cash balance
    account_equity: float | None = None
    average_entry: float | None = None
    mark_price: float | None = None
    liquidation_price: float | None = None

    def equity(self, price: float) -> float:
        """Mark-to-market equity in quote terms at `price`."""
        if self.account_equity is not None:
            return self.account_equity
        return self.cash + self.held * price


@dataclass
class LiveBroker:
    """Turns target positions into real spot or linear-swap orders."""

    client: TradeClient
    spec: MarketSpec
    min_base_amount: float = 0.0
    costs: CostModel = field(default_factory=CostModel)
    dust_fraction: float = DEFAULT_DUST_FRACTION
    rejections: list[Rejection] = field(default_factory=list)
    active_protection: ProtectiveOrder | None = field(default=None, init=False)

    def reconcile(self) -> Reconciliation:
        """Read normalized position and collateral from the exchange."""
        if self.spec.market_type == "swap":
            position = self.client.swap_position(self.spec.inst_id)
            balance = self.client.collateral_balance(quote_currency(self.spec.inst_id))
            return Reconciliation(
                held=position.quantity,
                cash=balance.cash,
                account_equity=balance.equity,
                average_entry=position.average_entry,
                mark_price=position.mark_price,
                liquidation_price=position.liquidation_price,
            )
        held = self.client.base_holding(self.spec.inst_id)
        cash = self.client.free_balance(quote_currency(self.spec.inst_id))
        return Reconciliation(held=held, cash=cash)

    def account_events(self, begin_ms: int, end_ms: int) -> list[AccountEvent]:
        """Funding/liquidation events already booked by OKX for this swap."""
        if self.spec.market_type != "swap":
            return []
        return self.client.swap_account_events(self.spec.inst_id, begin_ms, end_ms)

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
        signed_quantity = self.spec.round_quantity(held)
        quantity = abs(signed_quantity)
        if quantity == 0 or (stop_loss is None and take_profit is None):
            self.cancel_protection()
            return None
        if quantity < self.min_base_amount:
            raise TradeError(
                f"{self.spec.inst_id}: held quantity {quantity} is below protective-order "
                f"minimum {self.min_base_amount}; refusing to run unprotected"
            )

        side = Side.SELL if signed_quantity > 0 else Side.BUY
        desired = (quantity, stop_loss, take_profit, side)
        current = self.active_protection
        if current is not None and (
            current.quantity,
            current.stop_loss,
            current.take_profit,
            current.side,
        ) == desired:
            return current

        self.cancel_protection()
        algo_id = self.client.place_protective_order(
            self.spec.inst_id,
            side,
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
            side=side,
            client_order_id=client_order_id,
        )
        return self.active_protection
