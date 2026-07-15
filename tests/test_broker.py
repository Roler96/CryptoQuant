"""Tests for Broker — all mocked, no real exchange."""
import pytest
from unittest.mock import MagicMock, patch

from cryptoquant.exceptions import OrderRejectedError
from cryptoquant.execution.broker import Broker
from cryptoquant.execution.order import Order, OrderSide


@pytest.fixture
def mock_ccxt():
    with patch("cryptoquant.execution.broker.ccxt") as mock:
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock.okx = mock_cls
        import ccxt as real_ccxt

        # Exception types must be the real classes — Broker's retry and
        # order-lookup paths branch on isinstance/except against them, and
        # a MagicMock in an except clause raises TypeError instead.
        for name in (
            "NetworkError",
            "RateLimitExceeded",
            "AuthenticationError",
            "InsufficientFunds",
            "InvalidOrder",
            "OrderNotFound",
            "ExchangeError",
        ):
            setattr(mock, name, getattr(real_ccxt, name))
        yield mock, mock_instance


@pytest.fixture
def broker(mock_ccxt):
    _, mock_exchange = mock_ccxt
    return Broker(exchange="okx", testnet=True)


def _make_order(status="closed", side="buy", filled=1.0, amount=1.0):
    return {
        "id": "test-123",
        "symbol": "BTC/USDT",
        "side": side,
        "type": "market",
        "amount": amount,
        "price": 50000.0,
        "filled": filled,
        "remaining": amount - filled,
        "cost": filled * 50000.0,
        "fee": None,
        "status": status,
        "timestamp": 1704067200000,
    }


class TestBrokerInit:
    def test_testnet_mode(self, mock_ccxt):
        _, mock_exchange = mock_ccxt
        Broker(exchange="okx", testnet=True)
        mock_exchange.set_sandbox_mode.assert_called_once_with(True)

    def test_can_short_spot(self, broker):
        assert not broker.can_short

    def test_can_short_swap(self, mock_ccxt):
        _, mock_exchange = mock_ccxt
        broker = Broker(exchange="okx", testnet=True, account_type="swap")
        assert broker.can_short


class TestGetBalance:
    def test_returns_float(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.fetch_balance.return_value = {"USDT": {"free": 10000.0}}
        balance = broker.get_balance("USDT")
        assert balance == 10000.0

    def test_none_free_returns_zero(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.fetch_balance.return_value = {"USDT": {"free": None}}
        balance = broker.get_balance("USDT")
        assert balance == 0.0


class TestMarketOrders:
    def test_market_buy(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.create_market_buy_order.return_value = _make_order()
        order = broker.market_buy("BTC/USDT", 0.1)
        assert isinstance(order, Order)
        assert order.side == OrderSide.BUY

    def test_market_sell(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.create_market_sell_order.return_value = _make_order(side="sell")
        order = broker.market_sell("BTC/USDT", 0.1)
        assert order.side == OrderSide.SELL


class TestNormalizeOrderAmount:
    def test_applies_exchange_precision(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.amount_to_precision.return_value = "0.1234"
        mock_exchange.market.return_value = {
            "limits": {"amount": {"min": 0.001}, "cost": {"min": 10.0}}
        }

        amount = broker.normalize_order_amount("BTC/USDT", 0.123456, price=100000.0)

        assert amount == 0.1234
        mock_exchange.amount_to_precision.assert_called_once_with(
            "BTC/USDT", 0.123456
        )

    def test_rejects_below_min_amount(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.amount_to_precision.return_value = "0.0001"
        mock_exchange.market.return_value = {
            "limits": {"amount": {"min": 0.001}, "cost": {"min": 10.0}}
        }

        with pytest.raises(OrderRejectedError, match="below exchange min"):
            broker.normalize_order_amount("BTC/USDT", 0.0001, price=100000.0)

    def test_rejects_below_min_cost(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.amount_to_precision.return_value = "0.001"
        mock_exchange.market.return_value = {
            "limits": {"amount": {"min": 0.0001}, "cost": {"min": 10.0}}
        }

        with pytest.raises(OrderRejectedError, match="below exchange min cost"):
            broker.normalize_order_amount("BTC/USDT", 0.001, price=1000.0)


class TestGetPosition:
    def test_spot_no_position(self, broker, mock_ccxt):
        """Spot: no holdings → no position (even if exchange has free balance)."""
        _, mock_exchange = mock_ccxt
        # Even if exchange reports free balance, without strategy holdings it's None
        mock_exchange.fetch_balance.return_value = {"BTC": {"free": 0.5}}
        pos = broker.get_position("BTC/USDT")
        assert pos is None  # P0: strategy has no recorded holdings

    def test_spot_has_position(self, broker, mock_ccxt):
        """Spot: strategy holdings → position returned with correct entry price."""
        _, mock_exchange = mock_ccxt
        mock_exchange.fetch_ticker.return_value = {"last": 50000.0, "timestamp": 0}
        # Simulate a prior buy: 0.5 BTC at 48000
        broker.position_ledger.record_buy(
            "BTC/USDT", 0.5, 48000.0, fee=0.0, timestamp=1234
        )
        pos = broker.get_position("BTC/USDT")
        assert pos is not None
        assert pos.amount == 0.5
        assert pos.side == "long"
        assert pos.entry_price == 48000.0  # P0: correct entry price, not 0.0
        assert pos.timestamp == 1234

    def test_swap_amount_to_quote_uses_contract_size(self, mock_ccxt):
        _, mock_exchange = mock_ccxt
        broker = Broker(exchange="okx", testnet=True, account_type="swap")
        mock_exchange.market.return_value = {"contractSize": 10.0}

        assert broker.order_amount_to_quote(
            "DOGE/USDT:USDT", amount=2.0, price=0.2
        ) == pytest.approx(4.0)


class TestCancelOrder:
    def test_cancel_success(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.cancel_order.return_value = None
        assert broker.cancel_order("123", "BTC/USDT") is True

    def test_cancel_all(self, broker, mock_ccxt):
        _, mock_exchange = mock_ccxt
        mock_exchange.fetch_open_orders.return_value = [
            {"id": "1"},
            {"id": "2"},
            {"id": "3"},
        ]
        mock_exchange.cancel_order.return_value = None
        count = broker.cancel_all_orders("BTC/USDT")
        assert count == 3
