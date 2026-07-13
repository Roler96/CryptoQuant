"""Broker abstract base class."""
from abc import ABC, abstractmethod

from cryptoquant.execution.order import Order, Position


class BrokerABC(ABC):
    """Abstract base class for exchange broker implementations."""

    @property
    @abstractmethod
    def can_short(self) -> bool:
        """Whether the broker/account supports short positions."""
        ...

    @abstractmethod
    def get_balance(self, quote: str = "USDT") -> float:
        """Fetch free balance for a given quote currency."""
        ...

    @abstractmethod
    def get_ticker(self, symbol: str) -> dict:
        """Fetch ticker data for a symbol.

        Returns dict with keys: bid, ask, last, timestamp.
        """
        ...

    @abstractmethod
    def normalize_order_amount(
        self, symbol: str, amount: float, price: float | None = None
    ) -> float:
        """Round and validate base-asset order amount for this broker."""
        ...

    def quote_to_order_amount(
        self, symbol: str, quote_amount: float, price: float
    ) -> float:
        """Convert quote notional to the amount expected by the exchange.

        Spot brokers use base units; derivative brokers may use contracts.
        """
        if quote_amount <= 0 or price <= 0:
            return 0.0
        return quote_amount / price

    @abstractmethod
    def market_buy(self, symbol: str, amount: float) -> Order:
        """Execute a market buy order."""
        ...

    @abstractmethod
    def market_sell(self, symbol: str, amount: float) -> Order:
        """Execute a market sell order."""
        ...

    @abstractmethod
    def limit_buy(self, symbol: str, amount: float, price: float) -> Order:
        """Place a limit buy order."""
        ...

    @abstractmethod
    def limit_sell(self, symbol: str, amount: float, price: float) -> Order:
        """Place a limit sell order."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel a single open order."""
        ...

    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> int:
        """Cancel all open orders for a symbol.

        Returns number of orders cancelled.
        """
        ...

    @abstractmethod
    def get_open_orders(self, symbol: str) -> list[Order]:
        """Fetch all open orders for a symbol."""
        ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """Fetch current position for a symbol."""
        ...

    @abstractmethod
    def wait_for_fill(
        self, order_id: str, symbol: str, timeout: int = 30
    ) -> Order:
        """Poll until order is filled or terminal state reached."""
        ...

    @abstractmethod
    def fetch_order(self, order_id: str, symbol: str) -> Order:
        """Fetch a single order by ID."""
        ...

    @abstractmethod
    def reconnect(self) -> None:
        """Reload markets and reconnect to exchange."""
        ...
