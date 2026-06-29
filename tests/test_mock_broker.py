"""Tests for MockBroker."""
import pytest

from cryptoquant.execution.mock_broker import MockBroker
from cryptoquant.execution.order import OrderSide, OrderStatus, Position
from cryptoquant.exceptions import OrderRejectedError


class TestMockBroker:
    def test_is_instance_of_broker_abc(self):
        from cryptoquant.execution.broker_abc import BrokerABC
        broker = MockBroker()
        assert isinstance(broker, BrokerABC)

    def test_call_log_tracks_calls(self):
        broker = MockBroker()
        broker.get_balance()
        broker.get_ticker("BTC/USDT")
        assert len(broker.call_log) == 2
        assert broker.call_log[0]["method"] == "get_balance"
        assert broker.call_log[1]["method"] == "get_ticker"

    def test_configurable_balance(self):
        broker = MockBroker(balance=5000.0)
        assert broker.get_balance("USDT") == 5000.0

    def test_default_price(self):
        broker = MockBroker(default_price=100.0)
        ticker = broker.get_ticker("BTC/USDT")
        assert ticker["last"] == 100.0
        assert ticker["bid"] == 100.0
        assert ticker["ask"] == 100.0

    def test_position_state(self):
        pos = Position(
            symbol="BTC/USDT",
            side="long",
            amount=1.0,
            entry_price=100.0,
            current_price=100.0,
            unrealized_pnl=0.0,
            unrealized_pnl_abs=0.0,
            timestamp=0,
        )
        broker = MockBroker(position=pos)
        assert broker.get_position("BTC/USDT") == pos

    def test_market_buy_returns_closed_order(self):
        broker = MockBroker()
        order = broker.market_buy("BTC/USDT", 1.0)
        assert order.symbol == "BTC/USDT"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.CLOSED
        assert order.filled == 1.0

    def test_normalize_order_amount_logs_and_rounds(self):
        broker = MockBroker()
        amount = broker.normalize_order_amount("BTC/USDT", 0.123456789, price=100.0)
        assert amount == pytest.approx(0.12345679)
        assert broker.call_log[-1]["method"] == "normalize_order_amount"

    def test_normalize_order_amount_rejects_non_positive(self):
        broker = MockBroker()
        with pytest.raises(OrderRejectedError):
            broker.normalize_order_amount("BTC/USDT", 0.0)

    def test_market_sell_returns_closed_order(self):
        broker = MockBroker()
        order = broker.market_sell("BTC/USDT", 1.0)
        assert order.symbol == "BTC/USDT"
        assert order.side == OrderSide.SELL
        assert order.status == OrderStatus.CLOSED

    def test_wait_for_fill(self):
        broker = MockBroker()
        order = broker.market_buy("BTC/USDT", 1.0)
        filled = broker.wait_for_fill(order.id, "BTC/USDT")
        assert filled.id == order.id

    def test_fetch_order(self):
        broker = MockBroker()
        order = broker.market_buy("BTC/USDT", 1.0)
        fetched = broker.fetch_order(order.id, "BTC/USDT")
        assert fetched.id == order.id

    def test_cancel_order(self):
        broker = MockBroker()
        assert broker.cancel_order("1", "BTC/USDT") is True

    def test_cancel_all_orders(self):
        broker = MockBroker()
        assert broker.cancel_all_orders("BTC/USDT") == 0

    def test_get_open_orders_empty(self):
        broker = MockBroker()
        assert broker.get_open_orders("BTC/USDT") == []

    def test_reconnect_logs(self):
        broker = MockBroker()
        broker.reconnect()
        assert broker.call_log[-1]["method"] == "reconnect"

    def test_can_short_false(self):
        broker = MockBroker()
        assert broker.can_short is False

    def test_limit_buy_raises(self):
        broker = MockBroker()
        with pytest.raises(NotImplementedError):
            broker.limit_buy("BTC/USDT", 1.0, 100.0)

    def test_limit_sell_raises(self):
        broker = MockBroker()
        with pytest.raises(NotImplementedError):
            broker.limit_sell("BTC/USDT", 1.0, 100.0)
