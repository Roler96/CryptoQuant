"""Tests for AlertHandler rate limiting and deduplication."""

import time

from cryptoquant.monitor.alerts import AlertHandler


class FakeRecord:
    """Minimal loguru record mock."""

    def __init__(self, level_name: str, message: str):
        self.record = {
            "level": FakeLevel(level_name),
            "message": message,
            "time": FakeTime(),
            "name": "test",
            "function": "test_func",
            "line": 1,
        }


class FakeLevel:
    def __init__(self, name: str):
        self.name = name


class FakeTime:
    def isoformat(self):
        return time.strftime("%Y-%m-%dT%H:%M:%S")


class FakeMessage:
    def __init__(self, level_name: str, message: str):
        self.record = FakeRecord(level_name, message).record


class TestAlertHandler:
    """Alert handler tests (without network calls)."""

    def test_no_webhook_noop(self):
        handler = AlertHandler(webhook_url=None)
        msg = FakeMessage("CRITICAL", "test alert")
        # Should not raise
        handler(msg)

    def test_level_filtering(self):
        handler = AlertHandler(
            webhook_url="http://localhost/noop",
            alert_levels=("CRITICAL",),
        )
        msg = FakeMessage("INFO", "info msg")
        # Should be silently ignored (no webhook call)
        handler(msg)

    def test_rate_limit_enforced(self):
        handler = AlertHandler(
            webhook_url="http://localhost/noop",
            rate_limit_per_minute=2,
        )
        # First two should pass rate limit
        assert handler._check_rate_limit() is True
        assert handler._check_rate_limit() is True
        # Third should fail (within same minute)
        assert handler._check_rate_limit() is False

    def test_rate_limit_resets_after_window(self):
        handler = AlertHandler(
            webhook_url="http://localhost/noop",
            rate_limit_per_minute=1,
        )
        # Use one slot
        handler._check_rate_limit()
        # Manually expire the timestamp
        handler._sent_timestamps = [time.time() - 120]
        # Should pass again
        assert handler._check_rate_limit() is True

    def test_dedup_suppresses_duplicates(self):
        handler = AlertHandler(
            webhook_url="http://localhost/noop",
            dedup_window_seconds=300,
        )
        msg = "CRITICAL: exchange connection lost"
        assert handler._check_dedup(msg) is True  # First time
        assert handler._check_dedup(msg) is False  # Duplicate

    def test_dedup_different_messages_allowed(self):
        handler = AlertHandler(
            webhook_url="http://localhost/noop",
            dedup_window_seconds=300,
        )
        assert handler._check_dedup("alert one") is True
        assert handler._check_dedup("alert two") is True

    def test_dedup_expires_after_window(self):
        handler = AlertHandler(
            webhook_url="http://localhost/noop",
            dedup_window_seconds=1,
        )
        handler._check_dedup("test alert")
        time.sleep(1.1)
        assert handler._check_dedup("test alert") is True  # Expired
