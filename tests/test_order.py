"""Tests for Order and Position dataclasses."""
import pytest
from cryptoquant.execution.order import Order, OrderStatus, OrderSide, OrderType, Position


class TestOrder:
    def test_from_ccxt(self):
        raw = {
            "id": "123",
            "symbol": "BTC/USDT",
            "side": "buy",
            "type": "market",
            "amount": 0.1,
            "price": 50000.0,
            "filled": 0.1,
            "remaining": 0.0,
            "cost": 5000.0,
            "fee": {"cost": 5.0, "currency": "USDT"},
            "status": "closed",
            "timestamp": 1704067200000,
        }
        order = Order.from_ccxt(raw, exchange="okx")
        assert order.id == "123"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.CLOSED
        assert order.is_filled
        assert not order.is_open
        assert order.fill_pct == 100.0

    def test_is_open(self):
        order = Order(
            id="1",
            exchange="okx",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            amount=1.0,
            price=None,
            filled=0.0,
            remaining=1.0,
            cost=0.0,
            fee=None,
            status=OrderStatus.OPEN,
            timestamp=0,
        )
        assert order.is_open
        assert not order.is_filled

    def test_partially_filled(self):
        order = Order(
            id="1",
            exchange="okx",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            amount=1.0,
            price=50000.0,
            filled=0.5,
            remaining=0.5,
            cost=25000.0,
            fee=None,
            status=OrderStatus.PARTIALLY_FILLED,
            timestamp=0,
        )
        assert order.is_partially_filled
        assert order.fill_pct == 50.0

    def test_fill_pct_zero_amount(self):
        order = Order(
            id="1",
            exchange="okx",
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            amount=0.0,
            price=None,
            filled=0.0,
            remaining=0.0,
            cost=0.0,
            fee=None,
            status=OrderStatus.OPEN,
            timestamp=0,
        )
        assert order.fill_pct == 0.0


class TestPosition:
    def test_from_ccxt(self):
        raw = {
            "symbol": "BTC/USDT",
            "side": "long",
            "contracts": 0.5,
            "entryPrice": 50000.0,
            "markPrice": 51000.0,
            "unrealizedPnl": 500.0,
            "timestamp": 1704067200000,
        }
        pos = Position.from_ccxt(raw)
        assert pos.symbol == "BTC/USDT"
        assert pos.side == "long"
        assert pos.amount == 0.5
        assert pos.unrealized_pnl == pytest.approx(2.0)

    def test_notional(self):
        pos = Position(
            symbol="BTC/USDT",
            side="long",
            amount=0.5,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=2.0,
            unrealized_pnl_abs=500.0,
            timestamp=0,
        )
        assert pos.notional == 25500.0

    def test_zero_entry_price(self):
        raw = {
            "symbol": "BTC/USDT",
            "side": "long",
            "contracts": 1.0,
            "entryPrice": 0,
            "markPrice": 50000.0,
            "unrealizedPnl": 0,
            "timestamp": 0,
        }
        pos = Position.from_ccxt(raw)
        assert pos.unrealized_pnl == 0.0
