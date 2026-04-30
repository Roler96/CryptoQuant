"""Order management module for CryptoQuant live trading.

Provides order placement, cancellation, and status tracking for live trading
execution on OKX exchange.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

import structlog

from data.manager import OKXClient
from logs.audit import audit_trade


logger = structlog.get_logger(__name__)


class OrderSide(Enum):
    """Order side (buy or sell)."""
    BUY = auto()
    SELL = auto()


class OrderType(Enum):
    """Order type."""
    MARKET = auto()
    LIMIT = auto()
    STOP_LOSS = auto()
    STOP_LOSS_LIMIT = auto()
    TAKE_PROFIT = auto()
    TAKE_PROFIT_LIMIT = auto()


class OrderStatus(Enum):
    """Order execution status."""
    PENDING = auto()
    OPEN = auto()
    PARTIALLY_FILLED = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()
    EXPIRED = auto()


@dataclass
class Order:
    """Order data structure.

    Attributes:
        order_id: Unique order identifier (local)
        exchange_order_id: Exchange-assigned order ID
        pair: Trading pair symbol (e.g., "BTC/USDT")
        side: Order side (buy or sell)
        order_type: Order type (market, limit, etc.)
        status: Current order status
        amount: Order amount in base currency
        filled: Filled amount
        remaining: Remaining amount to fill
        price: Order price (for limit orders)
        average: Average fill price
        cost: Total cost in quote currency
        fee: Trading fee
        created_at: Timestamp when order was created
        updated_at: Timestamp of last update
        metadata: Additional order metadata
    """
    order_id: str
    pair: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    amount: Decimal
    price: Optional[Decimal] = None
    exchange_order_id: Optional[str] = None
    filled: Decimal = Decimal('0')
    remaining: Decimal = Decimal('0')
    average: Optional[Decimal] = None
    cost: Decimal = Decimal('0')
    fee: Decimal = Decimal('0')
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at: int = field(default_factory=lambda: int(time.time() * 1000))
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == OrderStatus.FILLED

    @property
    def is_active(self) -> bool:
        """Check if order is still active (open or partially filled)."""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @property
    def is_done(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED
        )

    def fill_ratio(self) -> Decimal:
        """Calculate fill ratio (0.0 to 1.0)."""
        if self.amount == 0:
            return Decimal('0')
        return self.filled / self.amount


@dataclass
class OrderResult:
    """Result of an order operation.

    Attributes:
        success: Whether the operation succeeded
        order: Order object if successful
        error_message: Error message if failed
        raw_response: Raw exchange response
    """
    success: bool
    order: Optional[Order] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class OrderManager:
    """Manages order placement, cancellation, and tracking for live trading.

    Handles communication with the OKX exchange via OKXClient for:
    - Creating and submitting orders
    - Cancelling open orders
    - Tracking order status and fills
    - Managing order history

    Attributes:
        client: OKXClient instance for exchange communication
        orders: Dictionary of tracked orders by local order ID
        pending_orders: Set of order IDs awaiting confirmation
    """

    def __init__(self, client: OKXClient) -> None:
        """Initialize order manager.

        Args:
            client: OKXClient instance for exchange communication
        """
        self.client = client
        self.orders: Dict[str, Order] = {}
        self.pending_orders: set = set()
        self.logger = structlog.get_logger(__name__)

    def _generate_order_id(self) -> str:
        """Generate unique local order ID.

        Returns:
            Unique order ID string
        """
        return f"ord_{uuid.uuid4().hex[:16]}"

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol format for OKX.

        Args:
            symbol: Symbol like "BTC/USDT" or "BTCUSDT"

        Returns:
            Normalized symbol for OKX (e.g., "BTC/USDT")
        """
        if '/' not in symbol:
            if symbol.endswith('USDT'):
                base = symbol[:-4]
                return f"{base}/USDT"
        return symbol

    def place_market_order(
        self,
        pair: str,
        side: OrderSide,
        amount: Decimal,
        metadata: Optional[Dict[str, Any]] = None
    ) -> OrderResult:
        """Place a market order.

        Market orders execute immediately at the best available price.

        Args:
            pair: Trading pair symbol
            side: Buy or sell
            amount: Order amount in base currency
            metadata: Optional metadata to attach to order

        Returns:
            OrderResult with order details or error
        """
        order_id = self._generate_order_id()
        normalized_pair = self._normalize_symbol(pair)

        order = Order(
            order_id=order_id,
            pair=normalized_pair,
            side=side,
            order_type=OrderType.MARKET,
            status=OrderStatus.PENDING,
            amount=amount,
            metadata=metadata or {}
        )

        self.orders[order_id] = order
        self.pending_orders.add(order_id)

        try:
            ccxt_side = 'buy' if side == OrderSide.BUY else 'sell'

            self.logger.info(
                "Placing market order",
                order_id=order_id,
                pair=normalized_pair,
                side=side.name,
                amount=str(amount)
            )

            response = self.client.exchange.create_market_buy_order(
                symbol=normalized_pair,
                amount=float(amount)
            ) if side == OrderSide.BUY else self.client.exchange.create_market_sell_order(
                symbol=normalized_pair,
                amount=float(amount)
            )

            order.exchange_order_id = response.get('id')
            order.status = OrderStatus.FILLED if response.get('filled', 0) > 0 else OrderStatus.OPEN
            order.filled = Decimal(str(response.get('filled', 0)))
            order.remaining = Decimal(str(response.get('remaining', 0)))
            order.average = Decimal(str(response.get('average', 0))) if response.get('average') else None
            order.cost = Decimal(str(response.get('cost', 0)))
            order.fee = Decimal(str(response.get('fee', {}).get('cost', 0)))
            order.updated_at = int(time.time() * 1000)

            self.pending_orders.discard(order_id)

            self.logger.info(
                "Market order placed successfully",
                order_id=order_id,
                exchange_order_id=order.exchange_order_id,
                status=order.status.name,
                filled=str(order.filled)
            )

            audit_trade(
                trade_id=order_id,
                strategy=metadata.get('strategy', 'live_trading'),
                pair=normalized_pair,
                side=ccxt_side,
                size=amount,
                entry_price=order.average or Decimal('0'),
                status='filled' if order.is_filled else 'open'
            )

            return OrderResult(success=True, order=order, raw_response=response)

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.updated_at = int(time.time() * 1000)
            self.pending_orders.discard(order_id)

            error_msg = str(e)
            self.logger.error(
                "Failed to place market order",
                order_id=order_id,
                error=error_msg
            )

            return OrderResult(success=False, order=order, error_message=error_msg)

    def place_limit_order(
        self,
        pair: str,
        side: OrderSide,
        amount: Decimal,
        price: Decimal,
        metadata: Optional[Dict[str, Any]] = None
    ) -> OrderResult:
        """Place a limit order.

        Limit orders execute at the specified price or better.

        Args:
            pair: Trading pair symbol
            side: Buy or sell
            amount: Order amount in base currency
            price: Limit price
            metadata: Optional metadata to attach to order

        Returns:
            OrderResult with order details or error
        """
        order_id = self._generate_order_id()
        normalized_pair = self._normalize_symbol(pair)

        order = Order(
            order_id=order_id,
            pair=normalized_pair,
            side=side,
            order_type=OrderType.LIMIT,
            status=OrderStatus.PENDING,
            amount=amount,
            price=price,
            metadata=metadata or {}
        )

        self.orders[order_id] = order
        self.pending_orders.add(order_id)

        try:
            ccxt_side = 'buy' if side == OrderSide.BUY else 'sell'

            self.logger.info(
                "Placing limit order",
                order_id=order_id,
                pair=normalized_pair,
                side=side.name,
                amount=str(amount),
                price=str(price)
            )

            response = self.client.exchange.create_limit_buy_order(
                symbol=normalized_pair,
                amount=float(amount),
                price=float(price)
            ) if side == OrderSide.BUY else self.client.exchange.create_limit_sell_order(
                symbol=normalized_pair,
                amount=float(amount),
                price=float(price)
            )

            order.exchange_order_id = response.get('id')
            order.status = OrderStatus.OPEN
            order.remaining = amount
            order.updated_at = int(time.time() * 1000)

            self.pending_orders.discard(order_id)

            self.logger.info(
                "Limit order placed successfully",
                order_id=order_id,
                exchange_order_id=order.exchange_order_id,
                status=order.status.name
            )

            return OrderResult(success=True, order=order, raw_response=response)

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.updated_at = int(time.time() * 1000)
            self.pending_orders.discard(order_id)

            error_msg = str(e)
            self.logger.error(
                "Failed to place limit order",
                order_id=order_id,
                error=error_msg
            )

            return OrderResult(success=False, order=order, error_message=error_msg)

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel an open order.

        Args:
            order_id: Local order ID to cancel

        Returns:
            OrderResult with updated order or error
        """
        order = self.orders.get(order_id)
        if not order:
            return OrderResult(
                success=False,
                error_message=f"Order {order_id} not found"
            )

        if not order.is_active:
            return OrderResult(
                success=False,
                order=order,
                error_message=f"Order {order_id} is not active (status: {order.status.name})"
            )

        try:
            self.logger.info(
                "Cancelling order",
                order_id=order_id,
                exchange_order_id=order.exchange_order_id
            )

            if order.exchange_order_id:
                response = self.client.exchange.cancel_order(
                    id=order.exchange_order_id,
                    symbol=order.pair
                )

                order.status = OrderStatus.CANCELLED
                order.updated_at = int(time.time() * 1000)

                self.logger.info(
                    "Order cancelled successfully",
                    order_id=order_id,
                    exchange_order_id=order.exchange_order_id
                )

                return OrderResult(success=True, order=order, raw_response=response)
            else:
                order.status = OrderStatus.CANCELLED
                order.updated_at = int(time.time() * 1000)
                return OrderResult(success=True, order=order)

        except Exception as e:
            error_msg = str(e)
            self.logger.error(
                "Failed to cancel order",
                order_id=order_id,
                error=error_msg
            )
            return OrderResult(success=False, order=order, error_message=error_msg)

    def cancel_all_orders(self, pair: Optional[str] = None) -> List[OrderResult]:
        """Cancel all open orders.

        Args:
            pair: Optional pair to filter by (cancels all if None)

        Returns:
            List of OrderResult for each cancellation attempt
        """
        results = []
        orders_to_cancel = [
            order for order in self.orders.values()
            if order.is_active and (pair is None or order.pair == self._normalize_symbol(pair))
        ]

        self.logger.info(
            "Cancelling all orders",
            count=len(orders_to_cancel),
            pair=pair
        )

        for order in orders_to_cancel:
            result = self.cancel_order(order.order_id)
            results.append(result)

        return results

    def update_order_status(self, order_id: str) -> OrderResult:
        """Update order status from exchange.

        Fetches latest order status from the exchange.

        Args:
            order_id: Local order ID to update

        Returns:
            OrderResult with updated order or error
        """
        order = self.orders.get(order_id)
        if not order:
            return OrderResult(
                success=False,
                error_message=f"Order {order_id} not found"
            )

        if not order.exchange_order_id:
            return OrderResult(
                success=True,
                order=order
            )

        try:
            response = self.client.exchange.fetch_order(
                id=order.exchange_order_id,
                symbol=order.pair
            )

            status_map = {
                'open': OrderStatus.OPEN,
                'closed': OrderStatus.FILLED,
                'canceled': OrderStatus.CANCELLED,
                'cancelled': OrderStatus.CANCELLED,
                'pending': OrderStatus.PENDING,
                'rejected': OrderStatus.REJECTED,
                'expired': OrderStatus.EXPIRED,
            }

            raw_status = response.get('status', '').lower()
            order.status = status_map.get(raw_status, OrderStatus.OPEN)

            order.filled = Decimal(str(response.get('filled', 0)))
            order.remaining = Decimal(str(response.get('remaining', 0)))
            order.average = Decimal(str(response.get('average', 0))) if response.get('average') else None
            order.cost = Decimal(str(response.get('cost', 0)))
            order.updated_at = int(time.time() * 1000)

            self.logger.debug(
                "Order status updated",
                order_id=order_id,
                status=order.status.name,
                filled=str(order.filled)
            )

            return OrderResult(success=True, order=order, raw_response=response)

        except Exception as e:
            error_msg = str(e)
            self.logger.error(
                "Failed to update order status",
                order_id=order_id,
                error=error_msg
            )
            return OrderResult(success=False, order=order, error_message=error_msg)

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID.

        Args:
            order_id: Local order ID

        Returns:
            Order object or None if not found
        """
        return self.orders.get(order_id)

    def get_open_orders(self, pair: Optional[str] = None) -> List[Order]:
        """Get all open orders.

        Args:
            pair: Optional pair to filter by

        Returns:
            List of open Order objects
        """
        normalized_pair = self._normalize_symbol(pair) if pair else None
        return [
            order for order in self.orders.values()
            if order.is_active and (normalized_pair is None or order.pair == normalized_pair)
        ]

    def get_order_history(
        self,
        pair: Optional[str] = None,
        limit: int = 100
    ) -> List[Order]:
        """Get order history.

        Args:
            pair: Optional pair to filter by
            limit: Maximum number of orders to return

        Returns:
            List of Order objects sorted by creation time (newest first)
        """
        normalized_pair = self._normalize_symbol(pair) if pair else None

        filtered = [
            order for order in self.orders.values()
            if normalized_pair is None or order.pair == normalized_pair
        ]

        sorted_orders = sorted(filtered, key=lambda o: o.created_at, reverse=True)
        return sorted_orders[:limit]

    def sync_orders(self, pair: Optional[str] = None) -> Dict[str, Any]:
        """Sync orders with exchange.

        Fetches all open orders from exchange and updates local state.

        Args:
            pair: Optional pair to filter by

        Returns:
            Dictionary with sync results
        """
        try:
            normalized_pair = self._normalize_symbol(pair) if pair else None

            if normalized_pair:
                open_orders = self.client.exchange.fetch_open_orders(symbol=normalized_pair)
            else:
                open_orders = self.client.exchange.fetch_open_orders()

            synced_count = 0
            for raw_order in open_orders:
                exchange_id = raw_order.get('id')

                existing = next(
                    (o for o in self.orders.values() if o.exchange_order_id == exchange_id),
                    None
                )

                if existing:
                    existing.status = OrderStatus.OPEN
                    existing.filled = Decimal(str(raw_order.get('filled', 0)))
                    existing.remaining = Decimal(str(raw_order.get('remaining', 0)))
                    existing.updated_at = int(time.time() * 1000)
                    synced_count += 1

            self.logger.info(
                "Orders synced with exchange",
                synced_count=synced_count,
                exchange_count=len(open_orders)
            )

            return {
                'success': True,
                'synced_count': synced_count,
                'exchange_count': len(open_orders)
            }

        except Exception as e:
            self.logger.error(
                "Failed to sync orders",
                error=str(e)
            )
            return {
                'success': False,
                'error': str(e)
            }

    def get_position_size(self, pair: str) -> Decimal:
        """Calculate current position size from filled orders.

        Args:
            pair: Trading pair symbol

        Returns:
            Net position size (positive for long, negative for short)
        """
        normalized_pair = self._normalize_symbol(pair)

        buy_filled = sum(
            order.filled for order in self.orders.values()
            if order.pair == normalized_pair
            and order.side == OrderSide.BUY
            and order.status == OrderStatus.FILLED
        )

        sell_filled = sum(
            order.filled for order in self.orders.values()
            if order.pair == normalized_pair
            and order.side == OrderSide.SELL
            and order.status == OrderStatus.FILLED
        )

        return buy_filled - sell_filled

    def clear_completed_orders(self, max_age_hours: int = 24) -> int:
        """Clear completed orders from memory.

        Args:
            max_age_hours: Only clear orders older than this many hours

        Returns:
            Number of orders cleared
        """
        current_time = int(time.time() * 1000)
        max_age_ms = max_age_hours * 3600 * 1000

        to_clear = [
            order_id for order_id, order in self.orders.items()
            if order.is_done and (current_time - order.updated_at) > max_age_ms
        ]

        for order_id in to_clear:
            del self.orders[order_id]

        self.logger.info(
            "Cleared completed orders",
            cleared_count=len(to_clear)
        )

        return len(to_clear)
