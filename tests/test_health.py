"""Tests for HealthChecker."""
import time
from unittest.mock import MagicMock

import pytest

from cryptoquant.monitor.health import HealthChecker, HealthStatus
from cryptoquant.risk.manager import DrawdownTier


@pytest.fixture
def checker():
    return HealthChecker(
        max_data_staleness_ms=300_000,
        min_balance_threshold=50.0,
    )


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_ticker.return_value = {"last": 50000.0}
    broker.get_balance.return_value = 10000.0
    return broker


@pytest.fixture
def mock_data_feed():
    feed = MagicMock()
    feed.last_fetch_ts = int(time.time() * 1000)
    return feed


@pytest.fixture
def mock_risk_manager():
    rm = MagicMock()
    rm.is_emergency_stop.return_value = False
    rm.current_tier.return_value = DrawdownTier.NORMAL
    return rm


class TestHealthCheck:
    def test_all_healthy(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert status.exchange_ok
        assert status.data_fresh
        assert status.balance_sane
        assert status.risk_ok
        assert status.last_check_ts > 0
        assert "exchange" in status.details
        assert "data" in status.details
        assert "balance" in status.details
        assert "risk" in status.details

    def test_exchange_failure(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        mock_broker.get_ticker.side_effect = Exception("network error")
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.exchange_ok
        assert "error" in status.details["exchange"]

    def test_data_stale(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        mock_data_feed.last_fetch_ts = 0
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.data_fresh
        assert "stale" in status.details["data"]

    def test_balance_low(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        mock_broker.get_balance.return_value = 10.0
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.balance_sane
        assert "10.0" in status.details["balance"]

    def test_risk_emergency(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        mock_risk_manager.is_emergency_stop.return_value = True
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.risk_ok
        assert "emergency" in status.details["risk"]

    def test_risk_drawdown_tier(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        mock_risk_manager.current_tier.return_value = DrawdownTier.HALT
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.risk_ok
        assert "halt" in status.details["risk"]

    def test_balance_error(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        mock_broker.get_balance.side_effect = Exception("auth failed")
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.balance_sane
        assert "error" in status.details["balance"]

    def test_data_error(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        from unittest.mock import PropertyMock
        type(mock_data_feed).last_fetch_ts = PropertyMock(side_effect=Exception("db locked"))
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        assert not status.data_fresh
        assert "error" in status.details["data"]

    def test_timestamp_set(self, checker, mock_broker, mock_data_feed, mock_risk_manager):
        before = int(time.time() * 1000)
        status = checker.check(mock_broker, mock_data_feed, mock_risk_manager)
        after = int(time.time() * 1000)
        assert before <= status.last_check_ts <= after


class TestHealthStatus:
    def test_dataclass_defaults(self):
        status = HealthStatus(
            exchange_ok=True,
            data_fresh=True,
            balance_sane=True,
            risk_ok=True,
            last_check_ts=1704067200000,
        )
        assert status.details == {}

    def test_dataclass_with_details(self):
        status = HealthStatus(
            exchange_ok=False,
            data_fresh=True,
            balance_sane=True,
            risk_ok=True,
            last_check_ts=1704067200000,
            details={"exchange": "timeout"},
        )
        assert status.details["exchange"] == "timeout"
