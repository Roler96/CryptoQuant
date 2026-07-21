"""Structural interface for a trading venue.

`LiveBroker` and the paper session depend on this rather than on
`OkxTradeClient`, so a deterministic test double is a first-class implementation
the type checker accepts — the same reason `cq.data.protocols` exists for the
market-data side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from cq.core.types import Fill, Side


@dataclass(frozen=True)
class ProtectiveOrder:
    """One resting market-on-trigger exit reported by the venue."""

    algo_id: str
    quantity: float
    stop_loss: float | None
    take_profit: float | None
    side: Side = Side.SELL
    client_order_id: str | None = None


MarginMode = Literal["cross", "isolated"]


@dataclass(frozen=True)
class SwapPosition:
    """One OKX linear-swap position, normalized to signed base quantity."""

    quantity: float
    average_entry: float | None
    mark_price: float | None
    liquidation_price: float | None
    leverage: float | None
    margin_mode: MarginMode | None


@dataclass(frozen=True)
class CollateralBalance:
    """Settlement-currency balances used by a derivative position."""

    cash: float
    equity: float
    available: float


AccountEventKind = Literal["funding", "liquidation", "adl"]


@dataclass(frozen=True)
class AccountEvent:
    """An exchange-side derivative balance event between strategy bars."""

    bill_id: str
    ts: int
    kind: AccountEventKind
    amount: float
    currency: str
    price: float | None
    quantity: float | None
    subtype: str


class TradeClient(Protocol):
    """What the live broker and paper session need from a venue."""

    def milliseconds(self) -> int: ...

    def free_balance(self, ccy: str) -> float: ...

    def base_holding(self, inst_id: str) -> float: ...

    def last_price(self, inst_id: str) -> float: ...

    def round_amount(self, inst_id: str, quantity: float) -> float: ...

    def market_order(
        self,
        inst_id: str,
        side: Side,
        quantity: float,
        reason: str = ...,
        client_order_id: str | None = ...,
    ) -> Fill: ...

    def place_protective_order(
        self,
        inst_id: str,
        side: Side,
        quantity: float,
        stop_loss: float | None = ...,
        take_profit: float | None = ...,
        client_order_id: str | None = ...,
    ) -> str: ...

    def cancel_algo_order(self, inst_id: str, algo_id: str) -> None: ...

    def pending_protective_orders(self, inst_id: str) -> list[ProtectiveOrder]: ...

    def protective_order_state(self, inst_id: str, algo_id: str) -> str: ...

    def configure_swap(
        self,
        inst_id: str,
        leverage: float,
        margin_mode: MarginMode = ...,
    ) -> None: ...

    def swap_position(self, inst_id: str) -> SwapPosition: ...

    def collateral_balance(self, ccy: str) -> CollateralBalance: ...

    def swap_account_events(
        self,
        inst_id: str,
        begin_ms: int,
        end_ms: int,
    ) -> list[AccountEvent]: ...
