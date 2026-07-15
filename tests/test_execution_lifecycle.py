"""Tests for ExecutionLifecycle — order submit, wait, partial fill, cancel."""

import pytest
from unittest.mock import MagicMock

from cryptoquant.exceptions import OrderRejectedError
from cryptoquant.execution.lifecycle import ExecutionLifecycle
from cryptoquant.execution.order import Order, OrderSide, OrderStatus, OrderType


def _make_order(
    status="closed", side="buy", filled=1.0, amount=1.0, price=50000.0
):
    return Order(
        id="test-123",
        exchange="okx",
        symbol="BTC/USDT",
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        type=OrderType.MARKET,
        amount=amount,
        price=price,
        filled=filled,
        remaining=amount - filled,
        cost=filled * price,
        fee=None,
        status=OrderStatus(status),
        timestamp=1704067200000,
    )


@pytest.fixture
def broker():
    b = MagicMock()
    b.exchange_name = "okx"
    b.market_buy.return_value = _make_order()
    b.market_sell.return_value = _make_order(side="sell")
    b.wait_for_fill.return_value = _make_order()
    b.cancel_order.return_value = True
    return b


@pytest.fixture
def executor(broker):
    return ExecutionLifecycle(broker, order_timeout=30)


class TestExecutionLifecycle:
    def test_buy_immediately_filled(self, executor, broker):
        """Market buy that fills immediately returns the order."""
        broker.market_buy.return_value = _make_order(status="closed")
        order = executor.execute_market("BTC/USDT", "buy", 0.1)

        assert order.is_filled
        assert order.side == OrderSide.BUY
        broker.market_buy.assert_called_once_with("BTC/USDT", 0.1)

    def test_sell_immediately_filled(self, executor, broker):
        """Market sell works same as buy."""
        broker.market_sell.return_value = _make_order(side="sell", status="closed")
        order = executor.execute_market("BTC/USDT", "sell", 0.1)

        assert order.is_filled
        assert order.side == OrderSide.SELL

    def test_waits_for_fill(self, executor, broker):
        """Order open → wait → filled."""
        broker.market_buy.return_value = _make_order(status="open", filled=0.0)
        broker.wait_for_fill.return_value = _make_order(status="closed")

        order = executor.execute_market("BTC/USDT", "buy", 0.1)

        assert order.is_filled
        broker.wait_for_fill.assert_called_once()

    def test_timeout_cancels_order(self, executor, broker):
        """Wait timeout → cancel → raise."""
        from cryptoquant.exceptions import ExecutionError

        broker.market_buy.return_value = _make_order(status="open", filled=0.0)
        broker.wait_for_fill.side_effect = ExecutionError("timeout")

        with pytest.raises(OrderRejectedError, match="not filled within"):
            executor.execute_market("BTC/USDT", "buy", 0.1)

        broker.cancel_order.assert_called_once_with("test-123", "BTC/USDT")

    def test_partial_fill_above_threshold_accepts(self, executor, broker):
        """≥90% filled → cancel remaining, mark closed."""
        partial = _make_order(
            status="partially_filled", filled=0.95, amount=1.0
        )
        broker.market_buy.return_value = partial
        # wait_for_fill returns the same partial — didn't fully fill
        broker.wait_for_fill.return_value = partial

        order = executor.execute_market("BTC/USDT", "buy", 1.0)

        assert order.status == OrderStatus.CLOSED
        assert order.amount == 0.95  # adjusted to filled amount
        # P0 fix: remaining MUST be cancelled
        broker.cancel_order.assert_called_once_with("test-123", "BTC/USDT")

    def test_partial_fill_cancel_failure_keeps_state_unknown(self, executor, broker):
        """A live remainder must never be relabelled as a closed order."""
        partial = _make_order(
            status="partially_filled", filled=0.95, amount=1.0
        )
        broker.market_buy.return_value = partial
        broker.wait_for_fill.return_value = partial
        broker.cancel_order.side_effect = RuntimeError("exchange unreachable")

        with pytest.raises(OrderRejectedError, match="state is unknown"):
            executor.execute_market("BTC/USDT", "buy", 1.0)

        assert partial.status == OrderStatus.PARTIALLY_FILLED
        assert partial.amount == 1.0

    def test_partial_fill_below_threshold_cancels(self, executor, broker):
        """<90% filled → cancel remaining."""
        partial = _make_order(
            status="partially_filled", filled=0.5, amount=1.0
        )
        broker.market_buy.return_value = partial
        broker.wait_for_fill.return_value = partial

        order = executor.execute_market("BTC/USDT", "buy", 1.0)

        assert order.amount == 0.5  # adjusted to filled amount
        assert order.remaining == 0.0
        assert order.status == OrderStatus.CLOSED
        broker.cancel_order.assert_called_once_with("test-123", "BTC/USDT")

    def test_small_partial_fill_cancel_failure_is_unknown(self, executor, broker):
        partial = _make_order(
            status="partially_filled", filled=0.5, amount=1.0
        )
        broker.market_buy.return_value = partial
        broker.wait_for_fill.return_value = partial
        broker.cancel_order.side_effect = RuntimeError("exchange unreachable")

        with pytest.raises(OrderRejectedError, match="state is unknown"):
            executor.execute_market("BTC/USDT", "buy", 1.0)

        assert partial.status == OrderStatus.PARTIALLY_FILLED
        assert partial.remaining == pytest.approx(0.5)

    def test_rejected_order_raises(self, executor, broker):
        """Immediately rejected → raise."""
        broker.market_buy.return_value = _make_order(status="rejected")

        with pytest.raises(OrderRejectedError, match="rejected"):
            executor.execute_market("BTC/USDT", "buy", 0.1)

    def test_invalid_side_raises(self, executor):
        with pytest.raises(ValueError, match="side must be"):
            executor.execute_market("BTC/USDT", "hold", 0.1)

    def test_paper_roundtrip_exposes_exact_realized_pnl(self):
        from cryptoquant.execution.paper_broker import PaperBroker
        from cryptoquant.position.ledger import ManagedPositionLedger

        paper = PaperBroker(
            initial_balance=1000.0,
            default_price=100.0,
            slippage_bps=0,
            commission_bps=100,
            latency_ms=0,
        )
        ledger = ManagedPositionLedger()
        executor = ExecutionLifecycle(paper, position_ledger=ledger)
        executor.execute_market("BTC/USDT", "buy", 1.0)
        paper.update_price("BTC/USDT", 90.0)

        executor.execute_market("BTC/USDT", "sell", 1.0)

        settlement = executor.last_closed_trade
        assert settlement is not None
        assert settlement.realized_pnl == pytest.approx(-11.9)

    def test_custom_threshold(self, broker):
        """Custom fill_threshold_pct is respected."""
        executor = ExecutionLifecycle(broker, fill_threshold_pct=50.0)
        partial = _make_order(
            status="partially_filled", filled=0.6, amount=1.0
        )
        broker.market_buy.return_value = partial
        broker.wait_for_fill.return_value = partial

        order = executor.execute_market("BTC/USDT", "buy", 1.0)

        # 60% ≥ 50% threshold → accepted
        assert order.status == OrderStatus.CLOSED
        assert order.amount == 0.6
