"""Structural interface for a trading venue.

`LiveBroker` and the paper session depend on this rather than on
`OkxTradeClient`, so a deterministic test double is a first-class implementation
the type checker accepts — the same reason `cq.data.protocols` exists for the
market-data side.
"""

from __future__ import annotations

from typing import Protocol

from cq.core.types import Fill, Side


class TradeClient(Protocol):
    """What the live broker and paper session need from a venue."""

    def milliseconds(self) -> int: ...

    def free_balance(self, ccy: str) -> float: ...

    def base_holding(self, inst_id: str) -> float: ...

    def last_price(self, inst_id: str) -> float: ...

    def round_amount(self, inst_id: str, quantity: float) -> float: ...

    def market_order(
        self, inst_id: str, side: Side, quantity: float, reason: str = ...
    ) -> Fill: ...
