"""Deterministic OKX client order ids for one closed-bar intent."""

from __future__ import annotations

import hashlib
from typing import Literal

OrderRole = Literal["target", "protection", "restore", "recovery"]

# OKX accepts up to 32 alphanumeric characters. Keeping ids inside signed
# int64 also makes OKX include clOrdId on its fills channel.
MAX_CLIENT_ORDER_ID = (1 << 63) - 1


def client_order_id(
    role: OrderRole,
    inst_id: str,
    ts: int,
    target: float,
    stop_loss: float | None,
    take_profit: float | None,
) -> str:
    """A stable positive numeric id for a role within one bar's intent."""
    payload = "|".join(
        (
            "cq-order-v1",
            role,
            inst_id,
            str(ts),
            target.hex(),
            "" if stop_loss is None else stop_loss.hex(),
            "" if take_profit is None else take_profit.hex(),
        )
    )
    digest = hashlib.sha256(payload.encode()).digest()
    value = int.from_bytes(digest[:8], "big") % (MAX_CLIENT_ORDER_ID - 1) + 1
    return str(value)
