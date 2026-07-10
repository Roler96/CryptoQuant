"""Execution lifecycle — order submission through fill/cancel.

Phase 2 module. Encapsulates the full order lifecycle that was previously
spread across LiveEngine._enter_position, _wait_and_handle_fill, and
_handle_partial_fill.

Handles: submit → wait → partial fill → cancel remaining → return result.
"""

from loguru import logger

from cryptoquant.exceptions import OrderRejectedError
from cryptoquant.execution.broker_abc import BrokerABC
from cryptoquant.execution.order import Order, OrderSide, OrderStatus


class ExecutionLifecycle:
    """Encapsulates order lifecycle: submit, wait, partial fill, cancel.

    Usage:
        executor = ExecutionLifecycle(broker, order_timeout=30)
        order = executor.execute_market("BTC/USDT", "buy", 0.1)
        if order.is_filled:
            logger.info(f"Filled {order.filled} @ {order.price}")
    """

    def __init__(
        self,
        broker: BrokerABC,
        order_timeout: int = 30,
        fill_threshold_pct: float = 90.0,
    ):
        self.broker = broker
        self.order_timeout = order_timeout
        self.fill_threshold_pct = fill_threshold_pct

    def execute_market(
        self, symbol: str, side: str, amount: float
    ) -> Order:
        """Submit a market order and see it through to completion.

        Lifecycle:
        1. Submit market buy/sell
        2. If not immediately filled, wait up to order_timeout seconds
        3. On partial fill >= fill_threshold_pct → accept as filled
        4. On partial fill < fill_threshold_pct → cancel remaining
        5. On timeout → cancel and raise

        Returns the final Order with updated status/amount.

        Raises OrderRejectedError on timeout or execution failure.
        """
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side}")

        # 1. Submit
        if side == "buy":
            order = self.broker.market_buy(symbol, amount)
        else:
            order = self.broker.market_sell(symbol, amount)

        # 2. Already filled
        if order.is_filled:
            return order

        # 3. Already in terminal state
        if order.status in (
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ):
            raise OrderRejectedError(
                f"Order {order.id} immediately {order.status.value}"
            )

        # 4. Wait for fill
        if order.is_open or order.is_partially_filled:
            order = self._wait_for_fill(order.id, symbol)

        # 5. Handle partial fill
        if order.is_partially_filled:
            order = self._handle_partial_fill(order)

        return order

    def _wait_for_fill(self, order_id: str, symbol: str) -> Order:
        """Wait for order to fill, with timeout."""
        try:
            return self.broker.wait_for_fill(
                order_id, symbol, timeout=self.order_timeout
            )
        except Exception:
            logger.warning(
                f"Order {order_id} timeout after {self.order_timeout}s, "
                f"cancelling"
            )
            try:
                self.broker.cancel_order(order_id, symbol)
            except Exception:
                logger.error(f"Failed to cancel order {order_id}")
            raise OrderRejectedError(
                f"Order {order_id} not filled within {self.order_timeout}s"
            )

    def _handle_partial_fill(self, order: Order) -> Order:
        """Handle partial fill: accept if above threshold, cancel if below."""
        if order.fill_pct >= self.fill_threshold_pct:
            logger.info(
                f"Order {order.id} {order.fill_pct:.1f}% filled, "
                f"treating as complete"
            )
            # P0 fix: MUST cancel remaining before marking closed.
            # Previously, remaining could fill later with no tracking.
            try:
                self.broker.cancel_order(order.id, order.symbol)
            except Exception:
                logger.warning(
                    f"Failed to cancel remaining for order {order.id}"
                )
            order.status = OrderStatus.CLOSED
            order.amount = order.filled
        else:
            logger.warning(
                f"Order {order.id} {order.fill_pct:.1f}% filled, "
                f"cancelling remaining {order.remaining}"
            )
            self.broker.cancel_order(order.id, order.symbol)
            order.amount = order.filled

        return order
