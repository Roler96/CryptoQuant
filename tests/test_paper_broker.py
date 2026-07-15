"""Tests for PaperBroker."""
from unittest.mock import patch
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

import pytest

from cryptoquant.execution.order import OrderSide, OrderStatus
from cryptoquant.execution.paper_broker import PaperBroker
from cryptoquant.exceptions import InsufficientFundsError, OrderRejectedError


class TestPaperBroker:
    def test_buy_reduces_balance(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
            commission_bps=0,
        )
        order = broker.market_buy("BTC/USDT", 10.0)
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.CLOSED
        assert broker.get_balance("USDT") == pytest.approx(9000.0)

    def test_sell_increases_balance(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
            commission_bps=0,
        )
        broker.market_buy("BTC/USDT", 10.0)
        order = broker.market_sell("BTC/USDT", 5.0)
        assert order.side == OrderSide.SELL
        assert broker.get_balance("USDT") == pytest.approx(9500.0)

    def test_position_tracking(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
        )
        broker.market_buy("BTC/USDT", 10.0)
        pos = broker.get_position("BTC/USDT")
        assert pos is not None
        assert pos.amount == 10.0
        assert pos.side == "long"
        broker.market_sell("BTC/USDT", 10.0)
        assert broker.get_position("BTC/USDT") is None

    def test_update_price_drives_ticker_and_position_pnl(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
        )
        broker.market_buy("BTC/USDT", 10.0)
        broker.update_price("BTC/USDT", 110.0)

        ticker = broker.get_ticker("BTC/USDT")
        pos = broker.get_position("BTC/USDT")
        assert ticker["last"] == pytest.approx(110.0)
        assert pos is not None
        assert pos.current_price == pytest.approx(110.0)
        assert pos.unrealized_pnl == pytest.approx(10.0)
        assert pos.unrealized_pnl_abs == pytest.approx(100.0)

    def test_scaling_position_preserves_entry_time_and_refreshes_pnl(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
            commission_bps=0,
        )
        broker.market_buy("BTC/USDT", 1.0)
        pos = broker.get_position("BTC/USDT")
        assert pos is not None
        pos.timestamp = 123
        broker.update_price("BTC/USDT", 110.0)

        broker.market_buy("BTC/USDT", 1.0)

        assert pos.timestamp == 123
        assert pos.entry_price == pytest.approx(105.0)
        assert pos.unrealized_pnl == pytest.approx((110 / 105 - 1) * 100)
        assert pos.unrealized_pnl_abs == pytest.approx(10.0)

        broker.market_sell("BTC/USDT", 0.5)
        assert pos.timestamp == 123
        assert pos.unrealized_pnl_abs == pytest.approx(7.5)

    def test_normalize_order_amount_rounds_to_paper_precision(self):
        broker = PaperBroker()
        assert broker.normalize_order_amount("BTC/USDT", 0.123456789) == pytest.approx(
            0.12345679
        )

    def test_normalize_order_amount_rejects_non_positive(self):
        broker = PaperBroker()
        with pytest.raises(OrderRejectedError):
            broker.normalize_order_amount("BTC/USDT", 0.0)

    def test_insufficient_balance_rejection(self):
        broker = PaperBroker(
            initial_balance=100.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
        )
        with pytest.raises(InsufficientFundsError):
            broker.market_buy("BTC/USDT", 2.0)

    def test_insufficient_position_rejection(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
        )
        with pytest.raises(InsufficientFundsError):
            broker.market_sell("BTC/USDT", 1.0)

    def test_slippage_applied_to_buy(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=100,
            latency_ms=0,
            commission_bps=0,
        )
        # 100 bps = 1% slippage
        order = broker.market_buy("BTC/USDT", 10.0)
        # Cost = 10 * 100 * 1.01 = 1010
        assert broker.get_balance("USDT") == pytest.approx(8990.0)
        pos = broker.get_position("BTC/USDT")
        assert pos is not None
        assert pos.entry_price == pytest.approx(order.price)

    def test_order_exposes_commission_for_settlement(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
            commission_bps=100,
        )

        order = broker.market_buy("BTC/USDT", 10.0)

        assert order.fee is not None
        assert order.fee["cost"] == pytest.approx(10.0)

    def test_slippage_applied_to_sell(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=100,
            latency_ms=0,
            commission_bps=0,
        )
        broker.market_buy("BTC/USDT", 10.0)
        broker.market_sell("BTC/USDT", 10.0)
        # Buy cost = 1010, sell proceeds = 10 * 100 * 0.99 = 990
        # Final balance = 10000 - 1010 + 990 = 9980
        assert broker.get_balance("USDT") == pytest.approx(9980.0)

    def test_commission_applied_to_buy(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
            commission_bps=100,
        )
        # 100 bps = 1% commission
        broker.market_buy("BTC/USDT", 10.0)
        # Cost = 10 * 100 + 1000 * 0.01 = 1010
        assert broker.get_balance("USDT") == pytest.approx(8990.0)

    def test_commission_applied_to_sell(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
            commission_bps=100,
        )
        broker.market_buy("BTC/USDT", 10.0)
        broker.market_sell("BTC/USDT", 10.0)
        # Buy cost = 1010, sell proceeds = 1000 - 10 = 990
        # Round trip charges commission on BOTH fills: 10000 - 1010 + 990 = 9980
        assert broker.get_balance("USDT") == pytest.approx(9980.0)

    def test_commission_is_charged_on_slipped_fill_not_reference_price(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=100,
            latency_ms=0,
            commission_bps=100,
        )

        buy = broker.market_buy("BTC/USDT", 10.0)
        sell = broker.market_sell("BTC/USDT", 10.0)

        assert buy.fee is not None and sell.fee is not None
        assert buy.fee["cost"] == pytest.approx(10.1)
        assert sell.fee["cost"] == pytest.approx(9.9)
        assert broker.get_balance("USDT") == pytest.approx(9960.0)

    def test_latency_sleep(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=50,
        )
        with patch("time.sleep") as mock_sleep:
            broker.market_buy("BTC/USDT", 1.0)
            mock_sleep.assert_called_once_with(0.05)

    def test_uses_paper_trading_config_defaults(self):
        from cryptoquant.config import PaperTradingConfig
        config = PaperTradingConfig()
        broker = PaperBroker()
        assert broker.get_balance("USDT") == pytest.approx(config.initial_balance)

    def test_average_down_position(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
        )
        broker.market_buy("BTC/USDT", 5.0)
        broker.market_buy("BTC/USDT", 5.0)
        pos = broker.get_position("BTC/USDT")
        assert pos is not None
        assert pos.amount == 10.0
        assert pos.entry_price == pytest.approx(100.0)

    def test_limit_orders_not_supported(self):
        broker = PaperBroker()
        with pytest.raises(NotImplementedError):
            broker.limit_buy("BTC/USDT", 1.0, 100.0)
        with pytest.raises(NotImplementedError):
            broker.limit_sell("BTC/USDT", 1.0, 100.0)

    def test_cancel_returns_false(self):
        broker = PaperBroker()
        assert broker.cancel_order("1", "BTC/USDT") is False
        assert broker.cancel_all_orders("BTC/USDT") == 0

    def test_get_open_orders_empty(self):
        broker = PaperBroker()
        assert broker.get_open_orders("BTC/USDT") == []

    def test_wait_and_fetch_order(self):
        broker = PaperBroker(
            initial_balance=10000.0,
            default_price=100.0,
            slippage_bps=0,
            latency_ms=0,
        )
        order = broker.market_buy("BTC/USDT", 1.0)
        fetched = broker.fetch_order(order.id, "BTC/USDT")
        assert fetched.id == order.id
        waited = broker.wait_for_fill(order.id, "BTC/USDT")
        assert waited.id == order.id

    def test_reconnect_noop(self):
        broker = PaperBroker()
        broker.reconnect()  # should not raise

    def test_can_short_false(self):
        broker = PaperBroker()
        assert broker.can_short is False
