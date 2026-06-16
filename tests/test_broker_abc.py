"""Tests for BrokerABC abstract base class."""
from unittest.mock import MagicMock, patch

import pytest

from cryptoquant.execution.broker import Broker
from cryptoquant.execution.broker_abc import BrokerABC


@pytest.fixture
def mock_ccxt():
    with patch("cryptoquant.execution.broker.ccxt") as mock:
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock.okx = mock_cls
        import ccxt as real_ccxt

        mock.NetworkError = real_ccxt.NetworkError
        mock.AuthenticationError = real_ccxt.AuthenticationError
        mock.InsufficientFunds = real_ccxt.InsufficientFunds
        mock.InvalidOrder = real_ccxt.InvalidOrder
        mock.ExchangeError = real_ccxt.ExchangeError
        yield mock, mock_instance


def test_broker_is_instance_of_abc(mock_ccxt):
    broker = Broker(exchange="okx", testnet=True)
    assert isinstance(broker, BrokerABC)


def test_broker_abc_has_all_expected_abstract_methods():
    abstract_methods = getattr(BrokerABC, "__abstractmethods__", set())
    expected = {
        "can_short",
        "get_balance",
        "get_ticker",
        "market_buy",
        "market_sell",
        "limit_buy",
        "limit_sell",
        "cancel_order",
        "cancel_all_orders",
        "get_open_orders",
        "get_position",
        "wait_for_fill",
        "fetch_order",
        "reconnect",
    }
    assert expected.issubset(abstract_methods)
