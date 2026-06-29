"""Mock broker for testing and CI — deterministic responses, no network calls."""
from cryptoquant.execution.broker_abc import BrokerABC
from cryptoquant.execution.order import Order, OrderSide, OrderStatus, OrderType, Position
from cryptoquant.exceptions import OrderRejectedError


class MockBroker(BrokerABC):
    """Deterministic broker mock with call logging.

    Tracks every method invocation in ``call_log`` for test assertions.
    """

    def __init__(
        self,
        balance: float = 10000.0,
        quote: str = "USDT",
        default_price: float = 50000.0,
        position: Position | None = None,
    ):
        self._balance = {quote: balance}
        self._quote = quote
        self._default_price = default_price
        self._position = position
        self._orders: dict[str, Order] = {}
        self._order_counter = 0
        self.call_log: list[dict] = []

    def _log(self, method: str, **kwargs) -> None:
        self.call_log.append({"method": method, **kwargs})

    @property
    def can_short(self) -> bool:
        self._log("can_short")
        return False

    def get_balance(self, quote: str = "USDT") -> float:
        self._log("get_balance", quote=quote)
        return self._balance.get(quote, 0.0)

    def get_ticker(self, symbol: str) -> dict:
        self._log("get_ticker", symbol=symbol)
        return {
            "bid": self._default_price,
            "ask": self._default_price,
            "last": self._default_price,
            "timestamp": 0,
        }

    def normalize_order_amount(
        self, symbol: str, amount: float, price: float | None = None
    ) -> float:
        self._log("normalize_order_amount", symbol=symbol, amount=amount, price=price)
        if amount <= 0:
            raise OrderRejectedError(f"Invalid order amount: {amount}")
        return round(amount, 8)

    def market_buy(self, symbol: str, amount: float) -> Order:
        self._log("market_buy", symbol=symbol, amount=amount)
        self._order_counter += 1
        order_id = f"mock-{self._order_counter}"
        order = Order(
            id=order_id,
            exchange="mock",
            symbol=symbol,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            amount=amount,
            price=self._default_price,
            filled=amount,
            remaining=0.0,
            cost=amount * self._default_price,
            fee=None,
            status=OrderStatus.CLOSED,
            timestamp=0,
        )
        self._orders[order_id] = order
        return order

    def market_sell(self, symbol: str, amount: float) -> Order:
        self._log("market_sell", symbol=symbol, amount=amount)
        self._order_counter += 1
        order_id = f"mock-{self._order_counter}"
        order = Order(
            id=order_id,
            exchange="mock",
            symbol=symbol,
            side=OrderSide.SELL,
            type=OrderType.MARKET,
            amount=amount,
            price=self._default_price,
            filled=amount,
            remaining=0.0,
            cost=amount * self._default_price,
            fee=None,
            status=OrderStatus.CLOSED,
            timestamp=0,
        )
        self._orders[order_id] = order
        return order

    def limit_buy(self, symbol: str, amount: float, price: float) -> Order:
        self._log("limit_buy", symbol=symbol, amount=amount, price=price)
        raise NotImplementedError("MockBroker does not support limit orders")

    def limit_sell(self, symbol: str, amount: float, price: float) -> Order:
        self._log("limit_sell", symbol=symbol, amount=amount, price=price)
        raise NotImplementedError("MockBroker does not support limit orders")

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        self._log("cancel_order", order_id=order_id, symbol=symbol)
        return True

    def cancel_all_orders(self, symbol: str) -> int:
        self._log("cancel_all_orders", symbol=symbol)
        return 0

    def get_open_orders(self, symbol: str) -> list[Order]:
        self._log("get_open_orders", symbol=symbol)
        return []

    def get_position(self, symbol: str) -> Position | None:
        self._log("get_position", symbol=symbol)
        return self._position

    def wait_for_fill(self, order_id: str, symbol: str, timeout: int = 30) -> Order:
        self._log("wait_for_fill", order_id=order_id, symbol=symbol, timeout=timeout)
        order = self._orders.get(order_id)
        if order is None:
            from cryptoquant.exceptions import ExecutionError
            raise ExecutionError(f"Order {order_id} not found")
        return order

    def fetch_order(self, order_id: str, symbol: str) -> Order:
        self._log("fetch_order", order_id=order_id, symbol=symbol)
        order = self._orders.get(order_id)
        if order is None:
            from cryptoquant.exceptions import ExecutionError
            raise ExecutionError(f"Order {order_id} not found")
        return order

    def reconnect(self) -> None:
        self._log("reconnect")
