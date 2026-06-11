"""Tests for monitor module."""
import pytest

from cryptoquant.monitor.journal import TradeJournal
from cryptoquant.monitor.reporter import Reporter
from cryptoquant.monitor.sanitizer import SanitizingLogger, sanitize
from cryptoquant.risk.manager import RiskManager


class TestTradeJournal:
    def test_record_and_load(self, tmp_path):
        journal = TradeJournal(journal_dir=str(tmp_path), strategy_name="test")
        journal.record({"symbol": "BTC/USDT", "pnl_pct": 1.5, "pnl_abs": 150.0})
        journal.record({"symbol": "ETH/USDT", "pnl_pct": -0.5, "pnl_abs": -50.0})

        trades = journal.load_all()
        assert len(trades) == 2
        assert trades[0]["symbol"] == "BTC/USDT"
        assert "recorded_at" in trades[0]

    def test_stats(self, tmp_path):
        journal = TradeJournal(journal_dir=str(tmp_path), strategy_name="test")
        journal.record({"pnl_pct": 2.0, "pnl_abs": 200.0})
        journal.record({"pnl_pct": -1.0, "pnl_abs": -100.0})
        journal.record({"pnl_pct": 3.0, "pnl_abs": 300.0})

        stats = journal.stats()
        assert stats["total"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert stats["win_rate"] == pytest.approx(66.67, abs=0.1)

    def test_empty_stats(self, tmp_path):
        journal = TradeJournal(journal_dir=str(tmp_path))
        stats = journal.stats()
        assert stats["total"] == 0

    def test_load_nonexistent(self, tmp_path):
        journal = TradeJournal(journal_dir=str(tmp_path / "nonexistent"))
        assert journal.load_all() == []


class TestSanitizer:
    def test_api_key_redacted(self):
        msg = 'api_key="abcdef1234567890"'
        result = sanitize(msg)
        assert "abcdef1234567890" not in result
        assert "REDACTED" in result

    def test_secret_redacted(self):
        msg = "secret: mysecretkey123456"
        result = sanitize(msg)
        assert "mysecretkey123456" not in result

    def test_password_redacted(self):
        msg = "password=hunter2secret"
        result = sanitize(msg)
        assert "hunter2secret" not in result

    def test_normal_message_unchanged(self):
        msg = "Market buy BTC/USDT amount=0.1"
        assert sanitize(msg) == msg


class TestSanitizingLogger:
    def test_wraps_logger(self):
        from unittest.mock import MagicMock

        mock_logger = MagicMock()
        safe = SanitizingLogger(mock_logger)
        safe.info("api_key=abcdef1234567890")
        mock_logger.info.assert_called_once()
        call_arg = mock_logger.info.call_args[0][0]
        assert "REDACTED" in call_arg


class TestReporter:
    def test_daily_summary(self, tmp_path):
        rm = RiskManager(initial_balance=10000.0)
        journal = TradeJournal(journal_dir=str(tmp_path))
        reporter = Reporter(rm, journal)

        summary = reporter.daily_summary()
        assert "Daily Trading Summary" in summary
        assert "10000" in summary

    def test_weekly_summary_empty(self, tmp_path):
        rm = RiskManager()
        journal = TradeJournal(journal_dir=str(tmp_path))
        reporter = Reporter(rm, journal)

        summary = reporter.weekly_summary()
        assert "No trades" in summary
