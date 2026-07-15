"""Order and Position data structures."""
from dataclasses import dataclass, field
from enum import Enum


class OrderStatus(str, Enum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Order:
    """Exchange order record."""

    id: str
    exchange: str
    symbol: str
    side: OrderSide
    type: OrderType
    amount: float
    price: float | None
    filled: float
    remaining: float
    cost: float
    fee: dict | None
    status: OrderStatus
    timestamp: int
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_ccxt(cls, raw: dict, exchange: str = "") -> "Order":
        return cls(
            id=str(raw.get("id", "")),
            exchange=exchange,
            symbol=raw.get("symbol", ""),
            side=OrderSide(raw["side"]),
            type=OrderType(raw.get("type", "market")),
            amount=float(raw.get("amount", 0)),
            price=float(raw["price"]) if raw.get("price") else None,
            filled=float(raw.get("filled", 0)),
            remaining=float(raw.get("remaining", 0)),
            cost=float(raw.get("cost", 0)),
            fee=raw.get("fee"),
            status=OrderStatus(raw.get("status", "open")),
            timestamp=raw.get("timestamp", 0),
            raw=raw,
        )

    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.CLOSED

    @property
    def is_open(self) -> bool:
        return self.status == OrderStatus.OPEN

    @property
    def is_partially_filled(self) -> bool:
        return self.status == OrderStatus.PARTIALLY_FILLED

    @property
    def fill_pct(self) -> float:
        if self.amount <= 0:
            return 0.0
        return self.filled / self.amount * 100


@dataclass
class Position:
    """Position record."""

    symbol: str
    side: str  # "long" | "short"
    amount: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    unrealized_pnl_abs: float
    timestamp: int

    @classmethod
    def from_ccxt(cls, raw: dict) -> "Position":
        entry_price = float(raw.get("entryPrice", raw.get("entry_price", 0)))
        current_price = float(raw.get("markPrice", raw.get("mark_price", 0)))
        side = raw.get("side", "long")

        if entry_price > 0:
            if side == "short":
                unrealized_pnl = (1 - current_price / entry_price) * 100
            else:
                unrealized_pnl = (current_price / entry_price - 1) * 100
        else:
            unrealized_pnl = 0.0

        return cls(
            symbol=raw.get("symbol", ""),
            side=side,
            amount=float(raw.get("contracts", raw.get("amount", 0))),
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_abs=float(raw.get("unrealizedPnl", 0)),
            timestamp=raw.get("timestamp", 0),
        )

    @property
    def notional(self) -> float:
        return self.amount * self.current_price
