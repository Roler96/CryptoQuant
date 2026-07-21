"""Structural interface for a trading venue.

`LiveBroker` and the paper session depend on this rather than on
`OkxTradeClient`, so a deterministic test double is a first-class implementation
the type checker accepts — the same reason `cq.data.protocols` exists for the
market-data side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
