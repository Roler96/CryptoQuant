"""Paper broker for simulated trading — market orders only (v1)."""
import time

from cryptoquant.config import PaperTradingConfig
from cryptoquant.exceptions import InsufficientFundsError, OrderRejectedError
from cryptoquant.execution.broker_abc import BrokerABC
from cryptoquant.execution.order import Order, OrderSide, OrderStatus, OrderType, Position


class PaperBroker(BrokerABC):
    """Simulated broker for paper trading.

    Market orders only (v1). Applies configurable slippage and latency,
    tracks virtual balance and positions.
    """

    def __init__(
        self,
        initial_balance: float | None = None,
        quote: str = "USDT",
        slippage_bps: float | None = None,
        latency_ms: int | None = None,
        default_price: float = 50000.0,
    ):
        config = PaperTradingConfig()
        self._balance: dict[str, float] = {
            quote: initial_balance if initial_balance is not None else config.initial_balance
        }
        self._quote = quote
        self._slippage = (
            slippage_bps if slippage_bps is not None else config.slippage_bps
        ) / 10_000
        self._latency_ms = (
            latency_ms if latency_ms is not None else config.latency_ms
        )
        self._prices: dict[str, float] = {}
        self._default_price = default_price
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._order_counter = 0

    @property
    def can_short(self) -> bool:
        return False

    def get_balance(self, quote: str = "USDT") -> float:
        return self._balance.get(quote, 0.0)

    def update_price(self, symbol: str, price: float) -> None:
        """Update simulated market price for a symbol."""
        if price <= 0:
            return
        self._prices[symbol] = price
        pos = self._positions.get(symbol)
        if pos is not None:
            pos.current_price = price
            if pos.entry_price > 0:
                pos.unrealized_pnl = (price / pos.entry_price - 1) * 100
                pos.unrealized_pnl_abs = (price - pos.entry_price) * pos.amount

    def get_ticker(self, symbol: str) -> dict:
        price = self._prices.get(symbol, self._default_price)
        return {
            "bid": price,
            "ask": price,
            "last": price,
            "timestamp": int(time.time() * 1000),
        }

    def normalize_order_amount(
        self, symbol: str, amount: float, price: float | None = None
    ) -> float:
        if amount <= 0:
            raise OrderRejectedError(f"Invalid order amount: {amount}")
        normalized = round(amount, 8)
        if normalized <= 0:
            raise OrderRejectedError(
                f"Order amount {amount} rounded to zero by paper precision"
            )
        return normalized

    def _sleep_latency(self) -> None:
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000)

    def _make_order(
        self, symbol: str, side: OrderSide, amount: float, price: float
    ) -> Order:
        self._order_counter += 1
        order_id = f"paper-{self._order_counter}"
        slippage_price = (
            price * (1 + self._slippage)
            if side == OrderSide.BUY
            else price * (1 - self._slippage)
        )
        order = Order(
            id=order_id,
            exchange="paper",
            symbol=symbol,
            side=side,
            type=OrderType.MARKET,
            amount=amount,
            price=round(slippage_price, 8),
            filled=amount,
            remaining=0.0,
            cost=round(amount * slippage_price, 8),
            fee=None,
            status=OrderStatus.CLOSED,
            timestamp=int(time.time() * 1000),
        )
        self._orders[order_id] = order
        return order

    def market_buy(self, symbol: str, amount: float) -> Order:
        self._sleep_latency()
        ticker = self.get_ticker(symbol)
        price = float(ticker["last"])
        cost = amount * price * (1 + self._slippage)
        if self._balance[self._quote] < cost:
            raise InsufficientFundsError(
                f"Insufficient balance: {self._balance[self._quote]:.4f} < {cost:.4f}"
            )
        self._balance[self._quote] -= cost

        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = Position(
                symbol=symbol,
                side="long",
                amount=amount,
                entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                unrealized_pnl_abs=0.0,
                timestamp=int(time.time() * 1000),
            )
        else:
            total_amount = pos.amount + amount
            avg_price = (pos.amount * pos.entry_price + amount * price) / total_amount
            pos.amount = total_amount
            pos.entry_price = avg_price
            pos.current_price = price
            pos.timestamp = int(time.time() * 1000)

        return self._make_order(symbol, OrderSide.BUY, amount, price)

    def market_sell(self, symbol: str, amount: float) -> Order:
        self._sleep_latency()
        ticker = self.get_ticker(symbol)
        price = float(ticker["last"])
        pos = self._positions.get(symbol)
        if pos is None or pos.amount < amount:
            raise InsufficientFundsError(
                f"Insufficient position: {pos.amount if pos else 0:.4f} < {amount:.4f}"
            )
        proceeds = amount * price * (1 - self._slippage)
        self._balance[self._quote] += proceeds
        pos.amount -= amount
        if pos.amount <= 0:
            del self._positions[symbol]
        else:
            pos.current_price = price
            pos.timestamp = int(time.time() * 1000)

        return self._make_order(symbol, OrderSide.SELL, amount, price)

    def limit_buy(self, symbol: str, amount: float, price: float) -> Order:
        raise NotImplementedError("Limit orders not supported in PaperBroker v1")

    def limit_sell(self, symbol: str, amount: float, price: float) -> Order:
        raise NotImplementedError("Limit orders not supported in PaperBroker v1")

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        return False

    def cancel_all_orders(self, symbol: str) -> int:
        return 0

    def get_open_orders(self, symbol: str) -> list[Order]:
        return []

    def get_position(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def wait_for_fill(
        self, order_id: str, symbol: str, timeout: int = 30
    ) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            from cryptoquant.exceptions import ExecutionError
            raise ExecutionError(f"Order {order_id} not found")
        return order

    def fetch_order(self, order_id: str, symbol: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            from cryptoquant.exceptions import ExecutionError
            raise ExecutionError(f"Order {order_id} not found")
        return order

    def reconnect(self) -> None:
        pass
